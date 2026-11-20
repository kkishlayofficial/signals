"""GET /api/bot/status, GET /api/bot/logs — connection health and the typed event log."""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import config
import database as db
from api.auth import require_token
from api.runtime import Runtime, get_runtime
from api.schemas import BotStatus, ConnectionStatus

_VALID_LEVELS = {"INFO", "WARNING", "ERROR", "DEBUG"}

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bot", tags=["bot"])


def _iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")


def _telegram_status(rt: Runtime) -> ConnectionStatus:
    listener = rt.listener
    if listener is None:
        return ConnectionStatus(connected=False, detail="not started")
    try:
        connected = bool(listener.client and listener.client.is_connected())
    except Exception as e:
        return ConnectionStatus(connected=False, detail=f"check failed: {e}")
    return ConnectionStatus(connected=connected, detail=None if connected else "disconnected")


def _angel_status(rt: Runtime) -> ConnectionStatus:
    broker = rt.broker
    if broker is None or not getattr(broker, "smart", None):
        return ConnectionStatus(connected=False, detail="not logged in")
    return ConnectionStatus(connected=True, detail=None)


def _market_feed_status(rt: Runtime) -> ConnectionStatus:
    tm = rt.trade_manager
    ticker = getattr(tm, "_ticker", None) if tm else None
    if ticker is None:
        return ConnectionStatus(connected=False, detail="WebSocket ticker not started (polling fallback active)")
    running = bool(getattr(ticker, "_running", False))
    return ConnectionStatus(connected=running, detail=None if running else "ticker not running")


@router.get("/status", response_model=BotStatus, dependencies=[Depends(require_token)])
async def bot_status(rt: Runtime = Depends(get_runtime)) -> BotStatus:
    tm = rt.trade_manager
    return BotStatus(
        mode=config.TRADING_MODE,
        paused=bool(getattr(tm, "paused", False)) if tm else False,
        uptime_seconds=rt.uptime_seconds(),
        started_at=_iso(rt.started_at),
        telegram=_telegram_status(rt),
        angel_broker=_angel_status(rt),
        market_feed=_market_feed_status(rt),
        last_signal_at=_iso(rt.last_signal_at),
        last_trade_at=_iso(rt.last_trade_at),
        last_tick_at=_iso(rt.last_tick_at),
        broker_errors=rt.errors.broker_errors,
        telegram_errors=rt.errors.telegram_errors,
        last_error=rt.errors.last_error,
        last_error_at=_iso(rt.errors.last_error_at),
    )


@router.post("/pause", response_model=BotStatus, dependencies=[Depends(require_token)])
async def pause_bot(rt: Runtime = Depends(get_runtime)) -> BotStatus:
    if rt.trade_manager is None:
        raise HTTPException(status_code=503, detail="Trade manager not available")
    rt.trade_manager.paused = True
    return await bot_status(rt)


@router.post("/resume", response_model=BotStatus, dependencies=[Depends(require_token)])
async def resume_bot(rt: Runtime = Depends(get_runtime)) -> BotStatus:
    if rt.trade_manager is None:
        raise HTTPException(status_code=503, detail="Trade manager not available")
    rt.trade_manager.paused = False
    return await bot_status(rt)


@router.get("/logs", dependencies=[Depends(require_token)])
async def bot_logs(
    level: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None, description="ISO 8601"),
    limit: int = Query(default=100, ge=1, le=500),
) -> List[Dict[str, Any]]:
    if level and level.upper() not in _VALID_LEVELS:
        raise HTTPException(status_code=422, detail=f"level must be one of {sorted(_VALID_LEVELS)}")
    return db.get_recent_bot_events(limit=limit, level=level, since=since)
