"""
End-to-end signal lifecycle through the REAL telegram_listener + trade_manager
code (not test doubles of them) -- only the broker is faked, since that's the
one dependency that needs a network. This is what actually proves
signal_id/instrument_token threading and the RECEIVED->PARSED->VALIDATED->
EXECUTED->CLOSED transitions work together, as opposed to each piece being
merely unit-testable in isolation.
"""
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import config
import database as db
import telegram_listener as tl
from api.events import EventBus
from api.runtime import ErrorCounters, runtime
from trade_manager import TradeManager

SAMPLE_SIGNAL = """
CRUDEOIL 17 NOV  8050 CE

ABOVE :- 120

STOPLOSS :- 90

Target 135/150
"""


class FakeBroker:
    """Enough of AngelBroker's interface for TradeManager, no network."""

    def __init__(self, ltp: float):
        self.ltp = ltp

    def find_instrument(self, **kwargs):
        return {
            "token": "99999", "symbol": "CRUDEOIL17NOV268050CE",
            "exch_seg": "MCX", "lotsize": 100, "ticksize": 0.05,
        }

    def get_ltp(self, exchange, tradingsymbol, token):
        return self.ltp


def _bare_listener(on_signal, on_targets=None) -> tl.TelegramListener:
    """
    A TelegramListener with __init__ skipped -- _handle_message never touches
    self.client, so this avoids constructing a real Telethon client (which
    would touch the live telegram.session file) just to test the
    signal/target pipeline around it.
    """
    listener = tl.TelegramListener.__new__(tl.TelegramListener)
    listener._last_activity = datetime.now(timezone.utc)
    listener.on_signal = on_signal
    listener.on_targets = on_targets
    return listener


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_trades.db"
        monkeypatch.setattr(config, "DB_PATH", path)
        # These tests are about the signal/trade lifecycle wiring, not risk
        # controls -- disable the live .env's caps so a 100-lot CRUDEOIL
        # contract at the sample entry price isn't itself rejected (12,000 >
        # the real MAX_CAPITAL_PER_TRADE of 10,000), which is correct
        # behaviour but not what this file is testing.
        monkeypatch.setattr(config, "MAX_CAPITAL_PER_TRADE", 0)
        monkeypatch.setattr(config, "MAX_OPEN_POSITIONS", 0)
        # Trailing stop is also a real .env feature, not part of what this
        # file tests -- leaving it on means reaching the first target arms
        # trailing instead of exiting there (by design, see trade_manager's
        # TRAILING_SL_AFTER_TARGET_ONLY), which isn't what these tests are
        # checking.
        monkeypatch.setattr(config, "TRAILING_SL_ENABLED", False)
        db.init_db()
        yield path


@pytest.fixture
def clean_runtime():
    runtime.bus = EventBus()
    runtime.errors = ErrorCounters()
    runtime.last_signal_at = None
    runtime.last_trade_at = None
    runtime.last_tick_at = None
    yield runtime


@pytest.mark.asyncio
async def test_full_signal_to_closed_lifecycle(temp_db, clean_runtime):
    # Price hasn't reached the 120 trigger yet -- that's a better price than
    # the signal asked for, so on_signal enters immediately at 100 instead of
    # parking the trade as PENDING and waiting for 120 to print.
    broker = FakeBroker(ltp=100.0)
    tm = TradeManager(broker=broker, notifier=None)
    listener = _bare_listener(on_signal=tm.on_signal, on_targets=tm.on_targets)

    # 1) Message arrives and is fully processed through the real pipeline.
    await listener._handle_message(SAMPLE_SIGNAL, quoted=None,
                                    channel_name="test-chan", msg_date=None)

    messages = db.get_recent_messages(limit=5)
    assert len(messages) == 1
    assert messages[0]["parse_result"] == "signal"
    assert messages[0]["trade_id"] is not None
    trade_id = messages[0]["trade_id"]

    signals = db.get_signals(limit=5)
    assert len(signals) == 1
    signal = signals[0]
    assert signal["status"] == "EXECUTED"
    assert signal["trade_id"] == trade_id
    assert signal["parsed_json"]["symbol"] == "CRUDEOIL"

    trade = db.get_trade(trade_id)
    assert trade["status"] == "ACTIVE"
    assert trade["entry_price"] == pytest.approx(100.0)
    assert trade["instrument_token"] == "99999"  # persisted from inst, not re-resolved later
    assert trade["signal_id"] == signal["id"]
    assert runtime.last_signal_at is not None
    assert runtime.last_trade_at is not None

    bot_events = db.get_recent_bot_events(limit=10)
    assert any(e["category"] == "ENTERED" for e in bot_events)

    # 2) Price reaches the first target -- the real exit path closes it.
    broker.ltp = 136.0
    await tm._tick()

    trade = db.get_trade(trade_id)
    assert trade["status"] == "CLOSED"
    assert trade["exit_reason"] == "TARGET_1"
    # (136 - 100) * 1 * 100 = 3600
    assert trade["pnl"] == pytest.approx(3600.0)

    signal = db.get_signal(signal["id"])
    assert signal["status"] == "CLOSED"

    exits = db.get_exits_for_trade(trade_id)
    assert len(exits) == 1
    assert exits[0]["reason"] == "TARGET_1"


@pytest.mark.asyncio
async def test_signal_within_stale_tolerance_still_enters(temp_db, clean_runtime):
    # Price has nudged 0.65 past the 120 "ABOVE" trigger -- within the
    # default ENTRY_STALE_TOLERANCE_POINTS (3), so this is still the same
    # entry window and should enter at the current price, not be discarded.
    broker = FakeBroker(ltp=120.65)
    tm = TradeManager(broker=broker, notifier=None)
    listener = _bare_listener(on_signal=tm.on_signal, on_targets=tm.on_targets)

    await listener._handle_message(SAMPLE_SIGNAL, quoted=None,
                                    channel_name="test-chan", msg_date=None)

    trade_id = db.get_recent_messages(limit=1)[0]["trade_id"]
    assert trade_id is not None
    trade = db.get_trade(trade_id)
    assert trade["status"] == "ACTIVE"
    assert trade["entry_price"] == pytest.approx(120.65)

    signal = db.get_signals(limit=1)[0]
    assert signal["status"] == "EXECUTED"


@pytest.mark.asyncio
async def test_stale_signal_is_discarded_not_queued(temp_db, clean_runtime):
    # Price has already run past the 120 "ABOVE" trigger by the time the
    # signal is processed -- the entry window is gone, so this must be
    # rejected outright, with no trade row left waiting around for it.
    broker = FakeBroker(ltp=130.0)
    tm = TradeManager(broker=broker, notifier=None)
    listener = _bare_listener(on_signal=tm.on_signal, on_targets=tm.on_targets)

    await listener._handle_message(SAMPLE_SIGNAL, quoted=None,
                                    channel_name="test-chan", msg_date=None)

    assert db.list_trades()["total"] == 0

    signals = db.get_signals(limit=5)
    assert len(signals) == 1
    assert signals[0]["status"] == "REJECTED"
    assert signals[0]["trade_id"] is None
    assert "stale" in signals[0]["reject_reason"]


@pytest.mark.asyncio
async def test_unparseable_signal_gets_invalid_status(temp_db, clean_runtime):
    tm = TradeManager(broker=FakeBroker(ltp=100.0), notifier=None)
    listener = _bare_listener(on_signal=tm.on_signal, on_targets=tm.on_targets)

    # Looks like a signal (has CE + ABOVE + "stoploss") but the stoploss sits
    # on the wrong side of entry for a BUY -- signal_parser rejects it.
    bad_text = "CRUDEOIL 17 NOV 8050 CE\n\nABOVE :- 120\n\nSTOPLOSS :- 150\n"
    await listener._handle_message(bad_text, quoted=None, channel_name="c", msg_date=None)

    signals = db.get_signals(limit=5)
    assert len(signals) == 1
    assert signals[0]["status"] == "INVALID"
    assert signals[0]["trade_id"] is None

    # No trade, no linked message -- a failed parse must not fabricate either.
    assert db.list_trades()["total"] == 0
    messages = db.get_recent_messages(limit=5)
    assert messages[0]["parse_result"] == "ignored"
    assert messages[0]["trade_id"] is None


@pytest.mark.asyncio
async def test_pure_chatter_gets_no_signal_row(temp_db, clean_runtime):
    tm = TradeManager(broker=FakeBroker(ltp=100.0), notifier=None)
    listener = _bare_listener(on_signal=tm.on_signal, on_targets=tm.on_targets)

    await listener._handle_message("good morning traders, market looks weak today",
                                   quoted=None, channel_name="c", msg_date=None)

    assert db.get_signals(limit=5) == []  # chatter never gets a lifecycle row
    messages = db.get_recent_messages(limit=5)
    assert messages[0]["parse_result"] == "ignored"


@pytest.mark.asyncio
async def test_duplicate_signal_links_to_existing_trade_not_a_new_one(temp_db, clean_runtime):
    tm = TradeManager(broker=FakeBroker(ltp=100.0), notifier=None)
    listener = _bare_listener(on_signal=tm.on_signal, on_targets=tm.on_targets)

    await listener._handle_message(SAMPLE_SIGNAL, quoted=None, channel_name="c", msg_date=None)
    first_trade_id = db.get_recent_messages(limit=1)[0]["trade_id"]

    # The channel reposts the identical call (common behaviour); it must not
    # open a second position.
    await listener._handle_message(SAMPLE_SIGNAL, quoted=None, channel_name="c", msg_date=None)

    assert db.list_trades()["total"] == 1
    signals = db.get_signals(limit=5)
    dup_signal = next(s for s in signals if s["status"] == "DUPLICATE")
    assert dup_signal["trade_id"] == first_trade_id
