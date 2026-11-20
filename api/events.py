"""
In-process event bus.

One bot, one process, one event source of truth — no Redis Pub/Sub needed
(that's for distributing events *across* processes; everything here already
lives in the same asyncio loop as the trade manager that produces them).

Every event gets a monotonically increasing `seq`. A ring buffer keeps the
last N events so a client that reconnects with `?since_seq=N` can replay what
it missed instead of silently losing events. Delivery to live subscribers is
at-least-once: each subscriber has its own bounded queue, and a slow consumer
that falls behind gets disconnected (its queue overflow trips a flag) rather
than being allowed to apply backpressure to emit() and stall the trade loop.
"""
import asyncio
import itertools
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

RING_SIZE = 500
SUBSCRIBER_QUEUE_SIZE = 200


@dataclass
class Event:
    seq: int
    id: str
    event: str
    timestamp: str
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "id": self.id,
            "event": self.event,
            "timestamp": self.timestamp,
            "data": self.data,
        }


@dataclass
class _Subscriber:
    queue: "asyncio.Queue[Event]" = field(default_factory=lambda: asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE))
    overflowed: bool = False


class EventBus:
    """
    Emit is synchronous and never awaits — called directly from
    TradeManager/TelegramListener code that runs on the bot's own tasks. It
    must never block on a slow subscriber.
    """

    def __init__(self, ring_size: int = RING_SIZE):
        self._seq = itertools.count(1)
        self._ring: deque[Event] = deque(maxlen=ring_size)
        self._subscribers: Dict[int, _Subscriber] = {}
        self._next_sub_id = itertools.count(1)
        self._lock_free_sub_counter = 0  # subscribers dict mutated only from the loop thread

    def emit(self, event: str, data: Dict[str, Any]) -> Event:
        evt = Event(
            seq=next(self._seq),
            id=f"evt-{uuid.uuid4().hex[:12]}",
            event=event,
            timestamp=_utc_now_iso(),
            data=data,
        )
        self._ring.append(evt)

        dead: List[int] = []
        for sub_id, sub in self._subscribers.items():
            try:
                sub.queue.put_nowait(evt)
            except asyncio.QueueFull:
                # Mark and drop rather than block the emitter (the trade
                # manager calling this must never stall on a slow browser).
                sub.overflowed = True
                dead.append(sub_id)
        for sub_id in dead:
            logger.warning(f"WS subscriber {sub_id} overflowed its queue; disconnecting it")
        return evt

    def subscribe(self) -> int:
        sub_id = next(self._next_sub_id)
        self._subscribers[sub_id] = _Subscriber()
        return sub_id

    def unsubscribe(self, sub_id: int):
        self._subscribers.pop(sub_id, None)

    async def next_event(self, sub_id: int, timeout: float = 15.0) -> Optional[Event]:
        """Wait for the next event for this subscriber, or None on timeout/overflow/missing."""
        sub = self._subscribers.get(sub_id)
        if sub is None:
            return None
        if sub.overflowed:
            return None
        try:
            return await asyncio.wait_for(sub.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def replay_since(self, since_seq: int) -> List[Event]:
        """Events strictly after since_seq still in the ring, oldest first."""
        return [e for e in self._ring if e.seq > since_seq]

    def oldest_seq(self) -> Optional[int]:
        return self._ring[0].seq if self._ring else None

    def latest_seq(self) -> int:
        return self._ring[-1].seq if self._ring else 0


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"
