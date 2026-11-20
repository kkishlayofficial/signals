"""
A plain async token bucket, used only to gate the NEW market-data broker
calls (candles, full quotes) that Phase 2 adds.

This never touches the trading loop's own broker calls (get_ltp, order
placement, order_state) -- those are pre-existing, time-critical, and stay
exactly as they were. Rate-limiting them is explicitly out of scope; this
class exists so a chatty terminal (many viewers scrolling through
instruments) can't hammer Angel's REST endpoints hard enough to risk a
429 or a session invalidation.
"""
import asyncio
import time


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: int):
        self.rate = rate_per_sec
        self.capacity = capacity
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self.rate
            await asyncio.sleep(wait)
