"""
Phase 1 database layer: migrations, signals/bot_events tables, pagination,
and the all-time stats aggregate used by /api/dashboard/overview.

Every test runs against its own temp SQLite file (config.DB_PATH is
monkeypatched per-test) -- never the real trades.db.
"""
import json
import tempfile
from pathlib import Path

import pytest

import config
import database as db


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_trades.db"
        monkeypatch.setattr(config, "DB_PATH", path)
        db.init_db()
        yield path


def _insert_sample_trade(status="PENDING", pnl=None, entry_price=None,
                         instrument_token=None, signal_id=None, charges=0):
    trade = {
        "mode": "paper", "symbol": "CRUDEOIL", "tradingsymbol": "CRUDEOIL17NOV268050CE",
        "exchange": "MCX", "option_type": "CE", "strike": 8050.0, "expiry": "17-NOV-2026",
        "action": "BUY", "quantity": 1, "lot_size": 100, "entry_condition": "ABOVE",
        "entry_trigger": 120.0, "stoploss": 90.0, "targets": [135.0, 150.0],
        "raw_signal": "CRUDEOIL 17 NOV 8050 CE ABOVE 120 SL 90 TGT 135/150",
        "targets_provisional": False,
        "instrument_token": instrument_token, "signal_id": signal_id,
    }
    trade_id = db.insert_trade(trade)
    if status in ("ACTIVE", "CLOSED"):
        db.mark_entered(trade_id, entry_price or 125.0, "PAPER-123")
    if status == "CLOSED":
        db.mark_exited(trade_id, entry_price or 125.0, "TARGET_1", pnl or 0.0)
        if charges:
            with db.connect() as c:
                c.execute("UPDATE trades SET charges = ? WHERE id = ?", (charges, trade_id))
    return trade_id


# ---------------------------------------------------------------- migrations

def test_migrations_add_new_columns(temp_db):
    with db.connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(trades)")}
    for col in ("instrument_token", "instrument_ticksize", "signal_id", "charges"):
        assert col in cols


def test_new_tables_exist(temp_db):
    with db.connect() as c:
        names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"signals", "bot_events", "candle_cache"} <= names


def test_init_db_is_idempotent(temp_db):
    db.init_db()
    db.init_db()  # must not raise on a second call


def test_old_row_survives_migration_with_null_new_columns(temp_db):
    trade_id = _insert_sample_trade()
    t = db.get_trade(trade_id)
    assert t["instrument_token"] is None  # not supplied in this call
    assert t["charges"] == 0


# ---------------------------------------------------------------- insert_trade persists new columns

def test_insert_trade_persists_instrument_token_and_signal_id(temp_db):
    trade_id = _insert_sample_trade(instrument_token="12345", signal_id=99)
    t = db.get_trade(trade_id)
    assert t["instrument_token"] == "12345"
    assert t["signal_id"] == 99


# ---------------------------------------------------------------- channel_messages linking

def test_insert_message_returns_id_and_can_be_linked(temp_db):
    msg_id = db.insert_message("test-channel", "hello", "signal")
    assert isinstance(msg_id, int)
    trade_id = _insert_sample_trade()
    db.update_message_trade(msg_id, trade_id)
    msgs = db.get_recent_messages(limit=10)
    linked = next(m for m in msgs if m["id"] == msg_id)
    assert linked["trade_id"] == trade_id


# ---------------------------------------------------------------- signals lifecycle

def test_signal_lifecycle_transitions(temp_db):
    sid = db.insert_signal(raw_text="CRUDEOIL 8050 CE ABOVE 120 SL 90", status="RECEIVED",
                           channel_name="chan")
    s = db.get_signal(sid)
    assert s["status"] == "RECEIVED"
    assert s["trade_id"] is None

    db.update_signal(sid, status="PARSED", parsed_json=json.dumps({"symbol": "CRUDEOIL"}))
    s = db.get_signal(sid)
    assert s["status"] == "PARSED"
    assert s["parsed_json"] == {"symbol": "CRUDEOIL"}  # decoded back to a dict

    trade_id = _insert_sample_trade(signal_id=sid)
    db.update_signal(sid, status="VALIDATED", trade_id=trade_id)
    s = db.get_signal(sid)
    assert s["status"] == "VALIDATED"
    assert s["trade_id"] == trade_id

    # A later update that omits reject_reason/trade_id must not clear them.
    db.update_signal(sid, status="EXECUTED")
    s = db.get_signal(sid)
    assert s["status"] == "EXECUTED"
    assert s["trade_id"] == trade_id  # preserved, not wiped by the COALESCE


def test_signal_reject_reason_is_set_and_preserved(temp_db):
    sid = db.insert_signal(raw_text="garbage text", status="RECEIVED")
    db.update_signal(sid, status="INVALID", reject_reason="no stoploss found")
    s = db.get_signal(sid)
    assert s["status"] == "INVALID"
    assert s["reject_reason"] == "no stoploss found"


def test_get_signals_filters_by_status_and_trade_id(temp_db):
    sid1 = db.insert_signal(raw_text="a", status="REJECTED")
    sid2 = db.insert_signal(raw_text="b", status="VALIDATED", trade_id=7)
    db.insert_signal(raw_text="c", status="VALIDATED", trade_id=8)

    rejected = db.get_signals(status="REJECTED")
    assert [s["id"] for s in rejected] == [sid1]

    for_trade = db.get_signals(trade_id=7)
    assert [s["id"] for s in for_trade] == [sid2]


# ---------------------------------------------------------------- bot_events

def test_log_bot_event_and_filter_by_level(temp_db):
    db.log_bot_event("INFO", "ENTERED", "entered trade #1")
    db.log_bot_event("ERROR", "ERROR", "broker call failed", data={"code": 500})

    all_events = db.get_recent_bot_events(limit=10)
    assert len(all_events) == 2

    errors = db.get_recent_bot_events(limit=10, level="ERROR")
    assert len(errors) == 1
    assert errors[0]["data_json"] == {"code": 500}


# ---------------------------------------------------------------- list_trades pagination/filters

def test_list_trades_pagination(temp_db):
    for _ in range(5):
        _insert_sample_trade(status="CLOSED", pnl=10.0)

    page1 = db.list_trades(page=1, page_size=2)
    assert page1["total"] == 5
    assert len(page1["items"]) == 2
    assert page1["page"] == 1

    page3 = db.list_trades(page=3, page_size=2)
    assert len(page3["items"]) == 1  # 5 rows, page_size 2 -> last page has 1


def test_list_trades_filters_by_status_and_profitability(temp_db):
    _insert_sample_trade(status="CLOSED", pnl=100.0)
    _insert_sample_trade(status="CLOSED", pnl=-50.0)
    _insert_sample_trade(status="PENDING")

    closed = db.list_trades(status="CLOSED")
    assert closed["total"] == 2

    winners = db.list_trades(status="CLOSED", profitable=True)
    assert winners["total"] == 1
    assert winners["items"][0]["pnl"] == 100.0

    losers = db.list_trades(status="CLOSED", profitable=False)
    assert losers["total"] == 1
    assert losers["items"][0]["pnl"] == -50.0


def test_list_trades_page_size_is_capped(temp_db):
    result = db.list_trades(page_size=10_000)
    assert result["page_size"] == 200  # capped, not 10000


# ---------------------------------------------------------------- overview aggregate

def test_alltime_stats_profit_factor_inputs(temp_db):
    _insert_sample_trade(status="CLOSED", pnl=300.0)
    _insert_sample_trade(status="CLOSED", pnl=-100.0)
    _insert_sample_trade(status="PENDING")  # must not count toward CLOSED aggregates

    stats = db.get_alltime_stats()
    assert stats["total"] == 3          # all trades, any status
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["realized_pnl"] == 200.0
    assert stats["gross_profit"] == 300.0
    assert stats["gross_loss"] == 100.0


def test_alltime_stats_total_charges(temp_db):
    _insert_sample_trade(status="CLOSED", pnl=100.0, charges=5.0)
    _insert_sample_trade(status="CLOSED", pnl=50.0, charges=3.0)
    stats = db.get_alltime_stats()
    assert stats["total_charges"] == 8.0
