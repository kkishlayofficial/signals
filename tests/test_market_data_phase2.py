"""
MarketDataService: instrument search/detail delegation, quote caching,
history's broker/tick-fallback decision, refcounted viewer subscriptions
(shared across multiple "connections", trade-held tokens never evicted),
and the live candle aggregation path.

All broker/ticker dependencies are fakes -- no network, no real Angel
session, no real DB except where the tick-fallback path genuinely needs
tick_history rows (via the same temp_db pattern used elsewhere).
"""
import tempfile
from pathlib import Path

import pytest

import api.market_data as md_module
import config
import database as db
from api.events import EventBus
from api.market_data import MarketDataService


class FakeBroker:
    def __init__(self):
        self.candles_by_token: dict = {}   # token -> list[candle] | Exception
        self.quote_by_token: dict = {}     # token -> FULL-mode row dict
        self.index: list = []
        self.candle_calls = 0
        self.quote_calls = 0

    def search_instruments(self, query, exchange, limit):
        q = query.upper()
        matches = [e for e in self.index if q in e["symbol"].upper()
                  and (exchange is None or e["exchange"] == exchange)]
        return matches[:limit]

    def get_instrument_by_token(self, exchange, token):
        for e in self.index:
            if e["exchange"] == exchange and e["token"] == str(token):
                return e
        return None

    def get_candles(self, exchange, token, interval, from_dt, to_dt):
        self.candle_calls += 1
        val = self.candles_by_token.get(str(token))
        if isinstance(val, Exception):
            raise val
        return val or []

    def get_market_data_full(self, exchange, tokens):
        self.quote_calls += 1
        fetched, unfetched = {}, []
        for t in tokens:
            row = self.quote_by_token.get(str(t))
            if row is None:
                unfetched.append(str(t))
            else:
                fetched[str(t)] = row
        return {"fetched": fetched, "unfetched": unfetched}


class FakeTicker:
    def __init__(self):
        self.subscribed: set = set()
        self.unsubscribe_calls: list = []

    def subscribe(self, exchange, token):
        self.subscribed.add((exchange, str(token)))

    def unsubscribe(self, exchange, token):
        self.subscribed.discard((exchange, str(token)))
        self.unsubscribe_calls.append((exchange, str(token)))


class FakeTradeManager:
    def __init__(self, ticker=None, ws_registry=None):
        self._ticker = ticker
        self._ws_registry = ws_registry or {}


class FakeRuntime:
    def __init__(self, broker=None, trade_manager=None):
        self.broker = broker
        self.trade_manager = trade_manager
        self.bus = EventBus()


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.db"
        monkeypatch.setattr(config, "DB_PATH", path)
        db.init_db()
        yield path


def _make_service(broker=None, ticker=None, ws_registry=None):
    rt = FakeRuntime(broker=broker, trade_manager=FakeTradeManager(ticker, ws_registry))
    return MarketDataService(rt), rt


# ---------------------------------------------------------------- instrument search

@pytest.mark.asyncio
async def test_search_instruments_delegates_to_broker():
    broker = FakeBroker()
    broker.index = [
        {"token": "1", "symbol": "CRUDEOIL17NOV268050CE", "name": "CRUDEOIL",
         "exchange": "MCX", "instrument_type": "OPTFUT", "expiry": "17NOV2026",
         "strike": 8050.0, "lotsize": 100, "tick_size": 0.1},
    ]
    svc, _ = _make_service(broker=broker)
    results = await svc.search_instruments("CRUDE", exchange="MCX", limit=10)
    assert len(results) == 1
    assert results[0]["token"] == "1"


@pytest.mark.asyncio
async def test_search_instruments_no_broker_returns_empty():
    svc, _ = _make_service(broker=None)
    assert await svc.search_instruments("ANY") == []


@pytest.mark.asyncio
async def test_get_instrument_not_found_returns_none():
    broker = FakeBroker()
    svc, _ = _make_service(broker=broker)
    assert await svc.get_instrument("MCX", "999") is None


# ---------------------------------------------------------------- quote

@pytest.mark.asyncio
async def test_get_quote_available():
    broker = FakeBroker()
    broker.quote_by_token["1"] = {
        "ltp": 125.5, "open": 120.0, "high": 130.0, "low": 118.0, "close": 119.0,
        "tradeVolume": 5000, "avgPrice": 124.0, "netChange": 6.5, "percentChange": 5.4,
        "depth": {"buy": [{"price": 125.0, "quantity": 10}], "sell": []},
    }
    svc, _ = _make_service(broker=broker)
    quote = await svc.get_quote("MCX", "1")
    assert quote["available"] is True
    assert quote["source"] == "broker"
    assert quote["ltp"] == 125.5
    assert quote["depth"]["available"] is True
    assert quote["stale"] is True  # no tick has ever arrived for this token


@pytest.mark.asyncio
async def test_get_quote_unfetched_is_unavailable():
    broker = FakeBroker()  # token not in quote_by_token -> unfetched
    svc, _ = _make_service(broker=broker)
    quote = await svc.get_quote("MCX", "1")
    assert quote["available"] is False
    assert quote["reason"] == "not returned by broker"


@pytest.mark.asyncio
async def test_get_quote_no_broker_is_unavailable_not_fabricated():
    svc, _ = _make_service(broker=None)
    quote = await svc.get_quote("MCX", "1")
    assert quote["available"] is False


@pytest.mark.asyncio
async def test_get_quote_is_cached_within_ttl():
    broker = FakeBroker()
    broker.quote_by_token["1"] = {"ltp": 100.0, "depth": {}}
    svc, _ = _make_service(broker=broker)
    await svc.get_quote("MCX", "1")
    await svc.get_quote("MCX", "1")
    assert broker.quote_calls == 1  # second call served from cache


@pytest.mark.asyncio
async def test_get_depth_reflects_quote():
    broker = FakeBroker()
    broker.quote_by_token["1"] = {
        "ltp": 100.0, "depth": {"buy": [{"price": 99.0, "quantity": 5}], "sell": []},
    }
    svc, _ = _make_service(broker=broker)
    depth = await svc.get_depth("MCX", "1")
    assert depth["available"] is True
    assert depth["bid"] == [{"price": 99.0, "quantity": 5}]


@pytest.mark.asyncio
async def test_get_depth_unavailable_when_quote_unavailable():
    broker = FakeBroker()
    svc, _ = _make_service(broker=broker)
    depth = await svc.get_depth("MCX", "1")
    assert depth["available"] is False


# ---------------------------------------------------------------- history

@pytest.mark.asyncio
async def test_history_uses_broker_when_sufficient(temp_db):
    from datetime import datetime, timedelta, timezone
    broker = FakeBroker()
    to_dt = datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)
    from_dt = to_dt - timedelta(minutes=25)  # 5 candles expected at 5m
    broker.candles_by_token["1"] = [
        {"ts": "2026-11-18T10:35:00", "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10},
        {"ts": "2026-11-18T10:40:00", "o": 100.5, "h": 102, "l": 100, "c": 101, "v": 12},
        {"ts": "2026-11-18T10:45:00", "o": 101, "h": 103, "l": 100.5, "c": 102, "v": 9},
        {"ts": "2026-11-18T10:50:00", "o": 102, "h": 104, "l": 101, "c": 103, "v": 15},
        {"ts": "2026-11-18T10:55:00", "o": 103, "h": 105, "l": 102, "c": 104, "v": 11},
    ]
    svc, _ = _make_service(broker=broker)
    result = await svc.get_history("MCX", "1", "5m", from_dt, to_dt)
    assert result["available"] is True
    assert result["source"] == "broker"
    assert len(result["candles"]) == 5

    cached = db.get_cached_candles("MCX", "1", "5m", "2026-11-18T00:00:00", "2026-11-19T00:00:00")
    assert len(cached) == 5  # the broker fetch warmed the cache


@pytest.mark.asyncio
async def test_history_falls_back_to_ticks_when_broker_empty(temp_db):
    from datetime import datetime, timedelta, timezone

    # A real trade with an instrument_token, so the tick-history JOIN finds it.
    trade = {
        "mode": "paper", "symbol": "CRUDEOIL", "tradingsymbol": "CRUDEOIL17NOV268050CE",
        "exchange": "MCX", "option_type": "CE", "strike": 8050.0, "expiry": "17-NOV-2026",
        "action": "BUY", "quantity": 1, "lot_size": 100, "entry_condition": "ABOVE",
        "entry_trigger": 120.0, "stoploss": 90.0, "targets": [135.0],
        "raw_signal": "x", "targets_provisional": False, "instrument_token": "1",
    }
    trade_id = db.insert_trade(trade)
    db.update_ltp(trade_id, 100.0)
    db.update_ltp(trade_id, 101.0)
    db.update_ltp(trade_id, 102.0)

    broker = FakeBroker()
    broker.candles_by_token["1"] = []  # empty response from the broker
    svc, _ = _make_service(broker=broker)

    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(hours=1)
    result = await svc.get_history("MCX", "1", "5m", from_dt, to_dt)
    assert result["available"] is True
    assert result["source"] == "ticks"
    assert len(result["candles"]) >= 1


@pytest.mark.asyncio
async def test_history_falls_back_to_ticks_when_broker_raises(temp_db):
    from datetime import datetime, timedelta, timezone
    trade = {
        "mode": "paper", "symbol": "CRUDEOIL", "tradingsymbol": "X", "exchange": "MCX",
        "option_type": "CE", "strike": 8050.0, "expiry": "17-NOV-2026", "action": "BUY",
        "quantity": 1, "lot_size": 100, "entry_condition": "ABOVE", "entry_trigger": 120.0,
        "stoploss": 90.0, "targets": [135.0], "raw_signal": "x", "targets_provisional": False,
        "instrument_token": "2",
    }
    trade_id = db.insert_trade(trade)
    db.update_ltp(trade_id, 50.0)

    broker = FakeBroker()
    broker.candles_by_token["2"] = RuntimeError("Angel API timeout")
    svc, _ = _make_service(broker=broker)

    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(hours=1)
    result = await svc.get_history("MCX", "2", "5m", from_dt, to_dt)
    assert result["source"] == "ticks"
    assert result["available"] is True


@pytest.mark.asyncio
async def test_history_unavailable_when_neither_source_has_data(temp_db):
    from datetime import datetime, timedelta, timezone
    broker = FakeBroker()
    broker.candles_by_token["404"] = []
    svc, _ = _make_service(broker=broker)
    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(hours=1)
    result = await svc.get_history("MCX", "404", "5m", from_dt, to_dt)
    assert result["available"] is False
    assert result["candles"] == []
    assert "no broker data" in result["reason"]


@pytest.mark.asyncio
async def test_history_rejects_unknown_interval(temp_db):
    from datetime import datetime, timedelta, timezone
    svc, _ = _make_service(broker=FakeBroker())
    to_dt = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        await svc.get_history("MCX", "1", "7m", to_dt - timedelta(hours=1), to_dt)


# ---------------------------------------------------------------- viewer subscriptions

def test_subscribe_viewer_refcount_shared_across_two_connections():
    ticker = FakeTicker()
    svc, _ = _make_service(ticker=ticker)
    svc.subscribe_viewer("MCX", "1", "5m")  # connection A
    svc.subscribe_viewer("MCX", "1", "5m")  # connection B, same token+interval
    assert ("MCX", "1") in ticker.subscribed

    svc.unsubscribe_viewer("1", "5m")  # A disconnects
    assert ("MCX", "1") in ticker.subscribed  # B still wants it -- must stay live

    svc.unsubscribe_viewer("1", "5m")  # B disconnects
    assert ("MCX", "1") not in ticker.subscribed
    assert ("MCX", "1") in ticker.unsubscribe_calls


def test_subscribe_viewer_never_unsubscribes_trade_held_token():
    ticker = FakeTicker()
    ticker.subscribed.add(("MCX", "1"))  # trade already has this live
    svc, _ = _make_service(ticker=ticker, ws_registry={"1": ({"token": "1"}, {42})})

    svc.subscribe_viewer("MCX", "1", "5m")
    svc.unsubscribe_viewer("1", "5m")
    # The viewer layer's own refcount hit zero, but the token is trade-held --
    # the ticker subscription must survive.
    assert ("MCX", "1") in ticker.subscribed
    assert ticker.unsubscribe_calls == []


def test_viewer_cap_evicts_least_recently_touched(monkeypatch):
    monkeypatch.setattr(md_module, "MAX_VIEWER_TOKENS", 2)
    ticker = FakeTicker()
    svc, _ = _make_service(ticker=ticker)

    svc.subscribe_viewer("MCX", "1", "5m")
    svc.subscribe_viewer("MCX", "2", "5m")
    svc.subscribe_viewer("MCX", "3", "5m")  # over the cap -- evicts token "1"

    assert "1" not in svc._viewer_subs
    assert ("MCX", "1") in ticker.unsubscribe_calls
    assert "2" in svc._viewer_subs
    assert "3" in svc._viewer_subs


def test_unsubscribe_viewer_different_interval_is_a_noop():
    ticker = FakeTicker()
    svc, _ = _make_service(ticker=ticker)
    svc.subscribe_viewer("MCX", "1", "5m")
    svc.unsubscribe_viewer("1", "15m")  # never subscribed at this interval
    assert ("MCX", "1") in ticker.subscribed  # the real 5m subscription is untouched


# ---------------------------------------------------------------- live candle aggregation

def test_update_forming_candle_emits_live_then_closes_on_rollover():
    svc, rt = _make_service()
    t0 = 1_700_000_000.0  # arbitrary epoch aligned to a 5m boundary by construction below
    t0 = (int(t0) // 300) * 300

    svc._update_forming_candle("1", "MCX", "5m", 100.0, t0)
    svc._update_forming_candle("1", "MCX", "5m", 105.0, t0 + 1)   # same bucket, new high
    svc._update_forming_candle("1", "MCX", "5m", 98.0, t0 + 2)    # same bucket, new low

    events = [e for e in rt.bus.replay_since(0) if e.event == "CANDLE_UPDATE"]
    assert all(e.data["closed"] is False for e in events)
    assert events[-1].data["h"] == 105.0
    assert events[-1].data["l"] == 98.0

    # Roll into the next 5-minute bucket.
    svc._update_forming_candle("1", "MCX", "5m", 110.0, t0 + 300)
    events = [e for e in rt.bus.replay_since(0) if e.event == "CANDLE_UPDATE"]
    closed_events = [e for e in events if e.data["closed"] is True]
    assert len(closed_events) == 1
    assert closed_events[0].data["c"] == 98.0  # the finished bucket's last price


def test_closed_candle_is_persisted_to_cache(temp_db):
    svc, rt = _make_service()
    t0 = (int(1_700_000_000.0) // 300) * 300
    svc._update_forming_candle("1", "MCX", "5m", 100.0, t0)
    svc._update_forming_candle("1", "MCX", "5m", 110.0, t0 + 300)  # closes the first bucket

    from datetime import datetime, timezone
    bucket_iso = datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(timespec="seconds")
    cached = db.get_cached_candles("MCX", "1", "5m", bucket_iso, bucket_iso)
    assert len(cached) == 1
    assert cached[0]["c"] == 100.0


def test_on_tick_delegates_only_for_subscribed_intervals():
    svc, _ = _make_service()
    svc.subscribe_viewer("MCX", "1", "5m")
    svc.on_tick("1", 123.4)
    assert ("1", "5m") in svc._forming

    svc.on_tick("2", 55.0)  # never subscribed -- must not create forming state
    assert not any(k[0] == "2" for k in svc._forming)


def test_is_stale_true_before_any_tick_false_after():
    svc, _ = _make_service()
    assert svc.is_stale("1") is True
    svc.on_tick("1", 100.0)
    assert svc.is_stale("1") is False
