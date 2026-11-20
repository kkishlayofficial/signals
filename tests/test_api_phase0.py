"""
Phase 0: EventBus, auth, Runtime, /api/bot/status, /ws.

Uses FastAPI's TestClient against the real app -- no live Angel/Telegram
connection is touched, and api.runtime.runtime is the real module-level
singleton the app reads from, reset between tests via the `clean_runtime`
fixture so tests don't leak state into each other.
"""
import time

import pytest
from fastapi.testclient import TestClient

import config
from api.app import app
from api.events import EventBus
from api.runtime import ErrorCounters, runtime


@pytest.fixture
def clean_runtime():
    """Reset the shared runtime singleton's mutable state before each test."""
    runtime.bus = EventBus()
    runtime.errors = ErrorCounters()
    runtime.broker = None
    runtime.trade_manager = None
    runtime.listener = None
    runtime.last_tick_at = None
    runtime.last_signal_at = None
    runtime.last_trade_at = None
    yield runtime


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    assert config.DASHBOARD_API_TOKEN, "DASHBOARD_API_TOKEN must be set in .env for tests"
    return {"Authorization": f"Bearer {config.DASHBOARD_API_TOKEN}"}


# ---------------------------------------------------------------- auth

def test_status_requires_auth(client, clean_runtime):
    r = client.get("/api/bot/status")
    assert r.status_code == 401


def test_status_rejects_wrong_token(client, clean_runtime):
    r = client.get("/api/bot/status", headers={"Authorization": "Bearer not-the-real-token"})
    assert r.status_code == 401


def test_status_accepts_valid_token(client, clean_runtime, auth_headers):
    r = client.get("/api/bot/status", headers=auth_headers)
    assert r.status_code == 200


def test_fails_closed_when_token_unconfigured(client, clean_runtime, monkeypatch):
    monkeypatch.setattr(config, "DASHBOARD_API_TOKEN", "")
    r = client.get("/api/bot/status", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503


# ---------------------------------------------------------------- status shape

def test_status_reports_disconnected_with_no_runtime_objects(client, clean_runtime, auth_headers):
    r = client.get("/api/bot/status", headers=auth_headers)
    body = r.json()
    assert body["mode"] == config.TRADING_MODE
    assert body["paused"] is False
    assert body["telegram"]["connected"] is False
    assert body["angel_broker"]["connected"] is False
    assert body["market_feed"]["connected"] is False
    assert body["broker_errors"] == 0
    assert body["last_signal_at"] is None


def test_status_reflects_paused_flag(client, clean_runtime, auth_headers):
    class FakeTM:
        paused = True

    clean_runtime.trade_manager = FakeTM()
    r = client.get("/api/bot/status", headers=auth_headers)
    assert r.json()["paused"] is True


def test_status_reflects_angel_login(client, clean_runtime, auth_headers):
    class FakeBroker:
        smart = object()  # truthy => "logged in" per _angel_status

    clean_runtime.broker = FakeBroker()
    r = client.get("/api/bot/status", headers=auth_headers)
    assert r.json()["angel_broker"]["connected"] is True


# ---------------------------------------------------------------- ws tickets

def test_ws_ticket_requires_auth(client, clean_runtime):
    r = client.post("/api/auth/ws-ticket")
    assert r.status_code == 401


def test_ws_rejects_missing_ticket(client, clean_runtime):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws"):
            pass


def test_ws_rejects_garbage_ticket(client, clean_runtime):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?ticket=not-a-real-ticket"):
            pass


def test_ws_ticket_is_single_use(client, clean_runtime, auth_headers):
    ticket = client.post("/api/auth/ws-ticket", headers=auth_headers).json()["ticket"]

    with client.websocket_connect(f"/ws?ticket={ticket}"):
        pass  # first use succeeds

    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws?ticket={ticket}"):
            pass  # second use must fail


# ---------------------------------------------------------------- ws transport

def test_ws_delivers_emitted_events(client, clean_runtime, auth_headers):
    ticket = client.post("/api/auth/ws-ticket", headers=auth_headers).json()["ticket"]

    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        runtime.bus.emit("TRADE_EXECUTED", {"trade_id": 1, "symbol": "TEST"})
        msg = ws.receive_json()
        assert msg["event"] == "TRADE_EXECUTED"
        assert msg["data"]["symbol"] == "TEST"
        assert msg["seq"] == 1
        assert "id" in msg and "timestamp" in msg


def test_ws_ping_pong(client, clean_runtime, auth_headers):
    ticket = client.post("/api/auth/ws-ticket", headers=auth_headers).json()["ticket"]
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        ws.send_json({"action": "ping"})
        reply = ws.receive_json()
        assert reply == {"event": "PONG"}


def test_ws_subscribe_ack(client, clean_runtime, auth_headers):
    ticket = client.post("/api/auth/ws-ticket", headers=auth_headers).json()["ticket"]
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        ws.send_json({"action": "subscribe", "channels": ["prices"], "tokens": ["99926000"]})
        reply = ws.receive_json()
        assert reply["event"] == "SUBSCRIPTION_ACK"
        assert reply["data"]["tokens"] == ["99926000"]


# ---------------------------------------------------------------- EventBus unit tests

def test_eventbus_seq_increments():
    bus = EventBus()
    e1 = bus.emit("A", {})
    e2 = bus.emit("B", {})
    assert e2.seq == e1.seq + 1


def test_eventbus_replay_since():
    bus = EventBus()
    for i in range(5):
        bus.emit("X", {"i": i})
    replayed = bus.replay_since(2)
    assert [e.data["i"] for e in replayed] == [2, 3, 4]


def test_eventbus_ring_buffer_bounded():
    bus = EventBus(ring_size=10)
    for i in range(50):
        bus.emit("X", {"i": i})
    assert len(bus._ring) == 10
    assert bus.oldest_seq() == 41  # last 10 of 1..50


def test_eventbus_emit_never_blocks_on_slow_subscriber():
    """emit() must return immediately even if a subscriber's queue is full."""
    bus = EventBus()
    sub_id = bus.subscribe()
    # Fill the subscriber's queue past capacity without ever calling next_event.
    from api.events import SUBSCRIBER_QUEUE_SIZE
    start = time.monotonic()
    for i in range(SUBSCRIBER_QUEUE_SIZE + 20):
        bus.emit("FLOOD", {"i": i})
    elapsed = time.monotonic() - start
    assert elapsed < 1.0  # no blocking, no sleeping, no backpressure
    assert bus._subscribers[sub_id].overflowed is True
