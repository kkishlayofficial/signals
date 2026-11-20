"""GET /api/market/quote, /api/market/history, /api/market/depth."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import require_token
from api.candles import INTERVALS, is_valid_interval
from api.runtime import Runtime, get_runtime
from api.schemas import DepthOut, HistoryOut, QuoteOut

router = APIRouter(prefix="/api/market", tags=["market"])

# How many candles' worth of history to default to when from/to aren't given.
DEFAULT_CANDLE_COUNT = 300
MAX_RANGE_DAYS = 90


def _require_market_data(rt: Runtime):
    if rt.market_data is None:
        raise HTTPException(status_code=503, detail="Market data service not ready")
    return rt.market_data


@router.get("/quote/{exchange}/{token}", response_model=QuoteOut, dependencies=[Depends(require_token)])
async def get_quote(exchange: str, token: str, rt: Runtime = Depends(get_runtime)):
    md = _require_market_data(rt)
    return await md.get_quote(exchange.upper(), token)


@router.get("/depth/{exchange}/{token}", response_model=DepthOut, dependencies=[Depends(require_token)])
async def get_depth(exchange: str, token: str, rt: Runtime = Depends(get_runtime)):
    md = _require_market_data(rt)
    return await md.get_depth(exchange.upper(), token)


@router.get("/history/{exchange}/{token}", response_model=HistoryOut, dependencies=[Depends(require_token)])
async def get_history(
    exchange: str, token: str,
    interval: str = Query(default="5m"),
    date_from: Optional[str] = Query(default=None, alias="from", description="ISO 8601"),
    date_to: Optional[str] = Query(default=None, alias="to", description="ISO 8601"),
    rt: Runtime = Depends(get_runtime),
):
    if not is_valid_interval(interval):
        raise HTTPException(status_code=422, detail=f"interval must be one of {sorted(INTERVALS)}")

    to_dt = _parse_dt(date_to) if date_to else datetime.now(timezone.utc)
    if date_from:
        from_dt = _parse_dt(date_from)
    else:
        from_dt = to_dt - timedelta(seconds=INTERVALS[interval].seconds * DEFAULT_CANDLE_COUNT)

    if from_dt >= to_dt:
        raise HTTPException(status_code=422, detail="'from' must be before 'to'")
    if (to_dt - from_dt) > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(status_code=422, detail=f"range may not exceed {MAX_RANGE_DAYS} days")

    md = _require_market_data(rt)
    return await md.get_history(exchange.upper(), token, interval, from_dt, to_dt)


def _parse_dt(raw: str) -> datetime:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid ISO 8601 datetime: {raw!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
