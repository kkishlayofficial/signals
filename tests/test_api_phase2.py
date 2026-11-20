"""
Phase 2 REST endpoints: /api/instruments, /api/market/quote, /api/market/history,
/api/market/depth -- against a seeded FakeBroker through the real FastAPI app.
"""
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import database as db
from api.app import app
from api.events import EventBus
from api.market_data import MarketDataService
from api.runtime import ErrorCounters, runtime
from tests.test_market_data_phase2 import FakeBroker, FakeTradeManager


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.db"
        monkeypatch.setattr(config, "DB_PATH", path)
        db.init_db()
        yield path


@pytest.fixture
def clean_runtime():
    runtime.bus = EventBus()
    runtime.errors = ErrorCounters()
    runtime.broker = None
    runtime.trade_manager = None
    runtime.listener = None
    runtime.market_data = None
    yield runtime


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    assert config.DASHBOARD_API_TOKEN
    return {"Authorization": f"Bearer {config.DASHBOARD_API_TOKEN}"}


def _wire_market_data(broker: FakeBroker) -> MarketDataService:
    runtime.broker = broker
    runtime.trade_manager = FakeTradeManager()
    svc = MarketDataService(runtime)
    runtime.market_data = svc
    return svc


# ---------------------------------------------------------------- instruments

def test_instruments_search_requires_auth(client, temp_db, clean_runtime):
    r = client.get("/api/instruments", params={"q": "CRUDE"})
    assert r.status_code == 401


def test_instruments_search_requires_query(client, temp_db, clean_runtime, auth_headers):
    r = client.get("/api/instruments", headers=auth_headers)
    assert r.status_code == 422  # q is required


def test_instruments_search_returns_matches(client, temp_db, clean_runtime, auth_headers):
    broker = FakeBroker()
    broker.index = [
        {"token": "1", "symbol": "CRUDEOIL17NOV268050CE", "name": "CRUDEOIL",
         "exchange": "MCX", "instrument_type": "OPTFUT", "expiry": "17NOV2026",
         "strike": 8050.0, "lotsize": 100, "tick_size": 0.1},
        {"token": "2", "symbol": "NIFTY23NOV2625100PE", "name": "NIFTY",
         "exchange": "NFO", "instrument_type": "OPTIDX", "expiry": "23NOV2026",
         "strike": 25100.0, "lotsize": 65, "tick_size": 0.05},
    ]
    _wire_market_data(broker)

    r = client.get("/api/instruments", params={"q": "CRUDE"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["token"] == "1"


def test_instrument_detail_404_when_missing(client, temp_db, clean_runtime, auth_headers):
    _wire_market_data(FakeBroker())
    r = client.get("/api/instruments/MCX/999", headers=auth_headers)
    assert r.status_code == 404


def test_instrument_detail_found(client, temp_db, clean_runtime, auth_headers):
    broker = FakeBroker()
    broker.index = [
        {"token": "1", "symbol": "CRUDEOIL17NOV268050CE", "name": "CRUDEOIL",
         "exchange": "MCX", "instrument_type": "OPTFUT", "expiry": "17NOV2026",
         "strike": 8050.0, "lotsize": 100, "tick_size": 0.1},
    ]
    _wire_market_data(broker)
    r = client.get("/api/instruments/MCX/1", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["symbol"] == "CRUDEOIL17NOV268050CE"


def test_instruments_503_when_service_not_ready(client, temp_db, clean_runtime, auth_headers):
    r = client.get("/api/instruments", params={"q": "X"}, headers=auth_headers)
    assert r.status_code == 503


# ---------------------------------------------------------------- quote / depth

def test_quote_requires_auth(client, temp_db, clean_runtime):
    r = client.get("/api/market/quote/MCX/1")
    assert r.status_code == 401


def test_quote_available(client, temp_db, clean_runtime, auth_headers):
    broker = FakeBroker()
    broker.quote_by_token["1"] = {
        "ltp": 125.5, "open": 120.0, "high": 130.0, "low": 118.0, "close": 119.0,
        "tradeVolume": 5000, "depth": {"buy": [], "sell": []},
    }
    _wire_market_data(broker)
    r = client.get("/api/market/quote/MCX/1", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["ltp"] == 125.5


def test_quote_unavailable_is_still_200_with_explicit_flag(client, temp_db, clean_runtime, auth_headers):
    _wire_market_data(FakeBroker())  # token never fetched -> unavailable
    r = client.get("/api/market/quote/MCX/1", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_depth_available(client, temp_db, clean_runtime, auth_headers):
    broker = FakeBroker()
    broker.quote_by_token["1"] = {
        "ltp": 100.0, "depth": {"buy": [{"price": 99.0, "quantity": 5}], "sell": []},
    }
    _wire_market_data(broker)
    r = client.get("/api/market/depth/MCX/1", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["bid"][0]["price"] == 99.0


# ---------------------------------------------------------------- history

def test_history_rejects_bad_interval(client, temp_db, clean_runtime, auth_headers):
    _wire_market_data(FakeBroker())
    r = client.get("/api/market/history/MCX/1", params={"interval": "7m"}, headers=auth_headers)
    assert r.status_code == 422


def test_history_rejects_from_after_to(client, temp_db, clean_runtime, auth_headers):
    _wire_market_data(FakeBroker())
    r = client.get(
        "/api/market/history/MCX/1",
        params={"interval": "5m", "from": "2026-11-18T12:00:00Z", "to": "2026-11-18T10:00:00Z"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_history_defaults_range_when_omitted(client, temp_db, clean_runtime, auth_headers):
    broker = FakeBroker()
    broker.candles_by_token["1"] = []
    _wire_market_data(broker)
    r = client.get("/api/market/history/MCX/1", params={"interval": "5m"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["available"] is False  # no broker data, no ticks -- honest, not fabricated


def test_history_returns_broker_candles(client, temp_db, clean_runtime, auth_headers):
    broker = FakeBroker()
    broker.candles_by_token["1"] = [
        {"ts": "2026-11-18T10:00:00+05:30", "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10},
    ]
    _wire_market_data(broker)
    # A 5-minute range expects exactly ~1 candle at 5m resolution -- 1 candle
    # isn't "sparse" here (unlike asking for an hour and getting back one).
    r = client.get(
        "/api/market/history/MCX/1",
        params={"interval": "5m", "from": "2026-11-18T04:00:00Z", "to": "2026-11-18T04:05:00Z"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["source"] == "broker"
    assert len(body["candles"]) == 1
