"""
Runtime holder.

A single mutable object that main.py populates once it has built the broker,
listener and trade manager, and that every API route reads through. This is
how the API gets access to the bot's *live* in-memory state (connection
status, pause flag, the WS ticker) without the API owning or re-creating any
of it.

Nothing in here does I/O. It's just references + small counters.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from api.events import EventBus

logger = logging.getLogger(__name__)


@dataclass
class ErrorCounters:
    broker_errors: int = 0
    telegram_errors: int = 0
    last_error: Optional[str] = None
    last_error_at: Optional[float] = None

    def record(self, category: str, message: str) -> None:
        if category == "broker":
            self.broker_errors += 1
        elif category == "telegram":
            self.telegram_errors += 1
        self.last_error = message[:500]
        self.last_error_at = time.time()


@dataclass
class Runtime:
    bus: EventBus = field(default_factory=EventBus)
    errors: ErrorCounters = field(default_factory=ErrorCounters)
    started_at: float = field(default_factory=time.time)

    # Populated by main.py once these objects exist. Typed loosely (Any) to
    # avoid a hard import cycle between api/ and the bot modules — the API
    # only ever calls documented methods on them.
    broker: Optional[Any] = None          # AngelBroker
    trade_manager: Optional[Any] = None   # TradeManager
    listener: Optional[Any] = None        # TelegramListener
    market_data: Optional[Any] = None     # MarketDataService (Phase 2)

    # Last-tick / last-signal bookkeeping for /api/bot/status. Updated via
    # small hooks called from trade_manager / telegram_listener, not by
    # reaching into their internals from here.
    last_tick_at: Optional[float] = None
    last_signal_at: Optional[float] = None
    last_trade_at: Optional[float] = None

    def mark_tick(self) -> None:
        self.last_tick_at = time.time()

    def mark_signal(self) -> None:
        self.last_signal_at = time.time()

    def mark_trade(self) -> None:
        self.last_trade_at = time.time()

    def uptime_seconds(self) -> float:
        return time.time() - self.started_at


# Process-wide singleton. main.py sets `runtime.broker = broker` etc. after
# constructing the bot; API routes import this same instance via get_runtime().
runtime = Runtime()


def get_runtime() -> Runtime:
    """FastAPI dependency."""
    return runtime
