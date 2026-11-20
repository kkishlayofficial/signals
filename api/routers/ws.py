"""
GET /ws?ticket=...&since_seq=N

Real-time event stream. See api/events.py for delivery semantics (at-least-
once, ring-buffer replay, per-subscriber bounded queue).

Wire protocol:
  server -> client : {"seq","id","event","timestamp","data"}  (see api/events.py)
             also   : {"event": "HEARTBEAT", "timestamp": ...}        every ~15s idle
  client -> server : {"action": "subscribe"|"unsubscribe",
                      "exchange": "MCX", "token": "12345", "interval": "5m"}
             also   : {"action": "ping"}  -> server replies {"event": "PONG"}

A subscribe/unsubscribe is per (exchange, token, interval) -- a client
watching the same instrument at two timeframes sends two subscribe messages
and should send two unsubscribe messages (or just disconnect; every
subscription this connection made is released on disconnect regardless).
This is what actually turns on live ticks for the token at the shared
ticker and starts live candle aggregation for it (see MarketDataService);
every connected client still receives every signal/trade lifecycle event
regardless of subscriptions -- those aren't token-scoped and aren't worth
filtering at this volume.
"""
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from api.auth import try_consume_ws_ticket
from api.runtime import runtime

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_IDLE_SECONDS = 15.0


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    ticket = websocket.query_params.get("ticket")
    since_seq_raw = websocket.query_params.get("since_seq")

    if not try_consume_ws_ticket(ticket):
        await websocket.close(code=4401)  # custom close code: auth failed
        return

    await websocket.accept()
    bus = runtime.bus
    sub_id = bus.subscribe()
    logger.info(f"WS client connected (sub_id={sub_id})")

    try:
        # Replay anything the client missed, oldest first, before live events.
        if since_seq_raw is not None:
            try:
                since_seq = int(since_seq_raw)
                for evt in bus.replay_since(since_seq):
                    await websocket.send_json(evt.to_dict())
            except ValueError:
                pass

        reader_task = None
        import asyncio

        # What THIS connection has subscribed to, so disconnect releases
        # exactly what it added -- never another connection's subscriptions
        # to the same (token, interval).
        my_subs: set = set()

        async def _reader():
            while True:
                msg = await websocket.receive_text()
                try:
                    payload = json.loads(msg)
                except (json.JSONDecodeError, TypeError):
                    continue
                action = payload.get("action")
                if action == "ping":
                    await websocket.send_json({"event": "PONG"})
                    continue
                if action not in ("subscribe", "unsubscribe"):
                    continue

                md = runtime.market_data
                exchange, token, interval = (
                    payload.get("exchange"), payload.get("token"), payload.get("interval"),
                )
                ok, error = True, None
                if not (exchange and token and interval):
                    ok, error = False, "exchange, token and interval are all required"
                elif md is None:
                    ok, error = False, "market data service not ready"
                else:
                    key = (exchange, str(token), interval)
                    try:
                        if action == "subscribe":
                            md.subscribe_viewer(exchange, token, interval)
                            my_subs.add(key)
                        else:
                            if key in my_subs:
                                md.unsubscribe_viewer(token, interval)
                                my_subs.discard(key)
                    except ValueError as e:
                        ok, error = False, str(e)

                reply = {"event": "SUBSCRIPTION_ACK", "data": {**payload, "ok": ok}}
                if error:
                    reply["data"]["error"] = error
                await websocket.send_json(reply)

        reader_task = asyncio.create_task(_reader())

        try:
            while True:
                evt = await bus.next_event(sub_id, timeout=HEARTBEAT_IDLE_SECONDS)
                if websocket.client_state != WebSocketState.CONNECTED:
                    break
                if evt is None:
                    await websocket.send_json({"event": "HEARTBEAT", "timestamp": _now_iso()})
                    continue
                await websocket.send_json(evt.to_dict())
        finally:
            reader_task.cancel()
            md = runtime.market_data
            if md is not None:
                for exchange, token, interval in my_subs:
                    try:
                        md.unsubscribe_viewer(token, interval)
                    except Exception as e:
                        logger.debug(f"cleanup unsubscribe failed for {token}/{interval}: {e}")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS handler error (sub_id={sub_id}): {e}")
    finally:
        bus.unsubscribe(sub_id)
        logger.info(f"WS client disconnected (sub_id={sub_id})")


def _now_iso() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
