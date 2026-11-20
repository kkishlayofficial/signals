"""
Phase 1 API: /api/dashboard/overview, /api/positions, /api/trades,
/api/trades/{id} against a seeded temp database, plus the redaction
guarantee -- no response body ever contains a credential, checked against
real HTTP response bytes, not by inspecting the serializer's source.
"""
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import database as db
from api.app import app
from api.events import EventBus
from api.runtime import ErrorCounters, runtime


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_trades.db"
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
    yield runtime


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    assert config.DASHBOARD_API_TOKEN
    return {"Authorization": f"Bearer {config.DASHBOARD_API_TOKEN}"}


def _insert_trade(status="PENDING", pnl=None, entry_price=125.0, current_ltp=None,
                  raw_signal="CRUDEOIL 17 NOV 8050 CE ABOVE 120 SL 90 TGT 135/150"):
    trade = {
        "mode": "paper", "symbol": "CRUDEOIL", "tradingsymbol": "CRUDEOIL17NOV268050CE",
        "exchange": "MCX", "option_type": "CE", "strike": 8050.0, "expiry": "17-NOV-2026",
        "action": "BUY", "quantity": 1, "lot_size": 100, "entry_condition": "ABOVE",
        "entry_trigger": 120.0, "stoploss": 90.0, "targets": [135.0, 150.0],
        "raw_signal": raw_signal, "targets_provisional": False,
        "instrument_token": "99926009",
    }
    trade_id = db.insert_trade(trade)
    if status in ("ACTIVE", "CLOSED"):
        db.mark_entered(trade_id, entry_price, "PAPER-1")
        if current_ltp is not None:
            db.update_ltp(trade_id, current_ltp)
    if status == "CLOSED":
        db.mark_exited(trade_id, entry_price if pnl is None else entry_price, "TARGET_1", pnl or 0.0)
    return trade_id


# ---------------------------------------------------------------- overview

def test_overview_requires_auth(client, temp_db, clean_runtime):
    r = client.get("/api/dashboard/overview")
    assert r.status_code == 401


def test_overview_matches_known_trades(client, temp_db, clean_runtime, auth_headers):
    _insert_trade(status="CLOSED", pnl=300.0)
    _insert_trade(status="CLOSED", pnl=-100.0)
    _insert_trade(status="ACTIVE", entry_price=125.0, current_ltp=130.0)
    _insert_trade(status="PENDING")

    r = client.get("/api/dashboard/overview", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()

    assert body["all_time"]["total_trades"] == 4
    assert body["all_time"]["wins"] == 1
    assert body["all_time"]["losses"] == 1
    assert body["all_time"]["realized_pnl"] == 200.0
    assert body["gross_profit"] == 300.0
    assert body["gross_loss"] == 100.0
    assert body["profit_factor"] == pytest.approx(3.0)
    assert body["win_rate"] == pytest.approx(0.5)
    assert body["active_positions"] == 1
    assert body["pending_signals"] == 1
    # (130 - 125) * 1 * 100 = 500
    assert body["unrealized_pnl"] == pytest.approx(500.0)


def test_overview_handles_zero_trades(client, temp_db, clean_runtime, auth_headers):
    r = client.get("/api/dashboard/overview", headers=auth_headers)
    body = r.json()
    assert body["all_time"]["total_trades"] == 0
    assert body["win_rate"] is None
    assert body["profit_factor"] is None
    assert body["active_positions"] == 0


# ---------------------------------------------------------------- positions

def test_positions_returns_only_open_trades(client, temp_db, clean_runtime, auth_headers):
    _insert_trade(status="PENDING")
    _insert_trade(status="ACTIVE", entry_price=125.0, current_ltp=130.0)
    _insert_trade(status="CLOSED", pnl=50.0)

    r = client.get("/api/positions", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert {i["status"] for i in items} == {"PENDING", "ACTIVE"}


def test_positions_unrealized_pnl_only_on_active(client, temp_db, clean_runtime, auth_headers):
    _insert_trade(status="PENDING")
    _insert_trade(status="ACTIVE", entry_price=125.0, current_ltp=130.0)

    r = client.get("/api/positions", headers=auth_headers)
    items = {i["status"]: i for i in r.json()}
    assert items["PENDING"]["unrealized_pnl"] is None
    assert items["ACTIVE"]["unrealized_pnl"] == pytest.approx(500.0)


# ---------------------------------------------------------------- trades (history)

def test_trades_list_pagination_and_sort(client, temp_db, clean_runtime, auth_headers):
    for pnl in (10.0, 50.0, -5.0):
        _insert_trade(status="CLOSED", pnl=pnl)

    r = client.get("/api/trades", params={"page_size": 2, "sort": "pnl_desc"}, headers=auth_headers)
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["items"][0]["pnl"] == 50.0
    assert body["items"][1]["pnl"] == 10.0


def test_trades_list_rejects_bad_status(client, temp_db, clean_runtime, auth_headers):
    r = client.get("/api/trades", params={"status": "NOT_A_STATUS"}, headers=auth_headers)
    assert r.status_code == 422


def test_trades_detail_includes_exits(client, temp_db, clean_runtime, auth_headers):
    trade_id = _insert_trade(status="CLOSED", pnl=42.0)
    r = client.get(f"/api/trades/{trade_id}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["trade"]["id"] == trade_id
    assert body["trade"]["pnl"] == 42.0
    assert len(body["exits"]) == 1
    assert body["exits"][0]["pnl"] == 42.0


def test_trades_detail_404_for_missing(client, temp_db, clean_runtime, auth_headers):
    r = client.get("/api/trades/99999", headers=auth_headers)
    assert r.status_code == 404


# ---------------------------------------------------------------- redaction
#
# raw_signal/notes are *meant* to pass through verbatim (they're trading-call
# text, shown raw on the Signals screen) -- so this test doesn't plant
# secret-looking substrings there, which would fail for the wrong reason.
# Instead it sets the actual config credential values to distinctive
# sentinels and asserts those exact sentinel strings never appear in any
# response body. A pass means the serializer allowlist genuinely excludes
# them, not merely that nothing sensitive happened to be in the DB.

_SENTINELS = {
    "ANGEL_API_KEY": "sentinel-angel-api-key-9f3e",
    "ANGEL_CLIENT_ID": "sentinel-angel-client-9f3e",
    "ANGEL_PASSWORD": "sentinel-angel-password-9f3e",
    "ANGEL_TOTP_SECRET": "sentinel-angel-totp-9f3e",
    "TELEGRAM_API_HASH": "sentinel-telegram-hash-9f3e",
    "TELEGRAM_PHONE": "sentinel-telegram-phone-9f3e",
    "DASHBOARD_API_TOKEN": "sentinel-dashboard-token-9f3e",
}


def test_no_endpoint_ever_leaks_credential_values(client, temp_db, clean_runtime, monkeypatch):
    for attr, value in _SENTINELS.items():
        monkeypatch.setattr(config, attr, value)
    headers = {"Authorization": f"Bearer {_SENTINELS['DASHBOARD_API_TOKEN']}"}

    trade_id = _insert_trade(status="CLOSED", pnl=10.0)

    class FakeBroker:
        smart = object()
        # If anything ever reached into the broker object for a status
        # field, these are what it would find -- named distinctly from the
        # config sentinels above so a leak here points at the broker path.
        access_token = "sentinel-broker-access-token-9f3e"
        feed_token = "sentinel-broker-feed-token-9f3e"
        refresh_token = "sentinel-broker-refresh-token-9f3e"

    runtime.broker = FakeBroker()

    endpoints = [
        "/api/bot/status",
        "/api/dashboard/overview",
        "/api/positions",
        "/api/trades",
        f"/api/trades/{trade_id}",
    ]
    for ep in endpoints:
        r = client.get(ep, headers=headers)
        assert r.status_code == 200, f"{ep} returned {r.status_code}"
        body_text = r.text
        for attr, value in _SENTINELS.items():
            assert value not in body_text, f"{ep} leaked {attr}"
        for leaked in ("sentinel-broker-access-token-9f3e",
                      "sentinel-broker-feed-token-9f3e",
                      "sentinel-broker-refresh-token-9f3e"):
            assert leaked not in body_text, f"{ep} leaked broker credential"


# ---------------------------------------------------------------- bot/logs (Phase 3 addition)

def test_bot_logs_requires_auth(client, temp_db, clean_runtime):
    r = client.get("/api/bot/logs")
    assert r.status_code == 401


def test_bot_logs_returns_recorded_events(client, temp_db, clean_runtime, auth_headers):
    db.log_bot_event("INFO", "ENTERED", "entered trade #1")
    db.log_bot_event("ERROR", "ERROR", "broker call failed")

    r = client.get("/api/bot/logs", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["message"] == "broker call failed"  # most recent first


def test_bot_logs_filters_by_level(client, temp_db, clean_runtime, auth_headers):
    db.log_bot_event("INFO", "ENTERED", "entered trade #1")
    db.log_bot_event("ERROR", "ERROR", "broker call failed")

    r = client.get("/api/bot/logs", params={"level": "ERROR"}, headers=auth_headers)
    body = r.json()
    assert len(body) == 1
    assert body[0]["level"] == "ERROR"


def test_bot_logs_rejects_bad_level(client, temp_db, clean_runtime, auth_headers):
    r = client.get("/api/bot/logs", params={"level": "VERBOSE"}, headers=auth_headers)
    assert r.status_code == 422
