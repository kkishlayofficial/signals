"""GET /api/trades, GET /api/trades/{id} — paginated history + detail."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import database as db
from api.auth import require_token
from api.schemas import PaginatedTrades, TradeDetail, TradeSource
from api.serializers import (serialize_channel_message, serialize_exit,
                             serialize_signal, serialize_trade)

router = APIRouter(prefix="/api/trades", tags=["trades"])

_VALID_SORT = {"id_desc", "id_asc", "pnl_desc", "pnl_asc", "created_desc", "created_asc"}
_VALID_STATUS = {"PENDING", "ACTIVE", "CLOSED", "CANCELLED"}


@router.get("", response_model=PaginatedTrades, dependencies=[Depends(require_token)])
async def list_trades(
    status: Optional[str] = Query(default=None),
    instrument: Optional[str] = Query(default=None),
    profitable: Optional[bool] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort: str = Query(default="id_desc"),
):
    if status and status.upper() not in _VALID_STATUS:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUS)}")
    if sort not in _VALID_SORT:
        raise HTTPException(status_code=422, detail=f"sort must be one of {sorted(_VALID_SORT)}")

    result = db.list_trades(
        status=status, instrument=instrument, profitable=profitable,
        date_from=date_from, date_to=date_to, page=page, page_size=page_size, sort=sort,
    )
    return {
        "items": [serialize_trade(r) for r in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }


@router.get("/{trade_id}", response_model=TradeDetail, dependencies=[Depends(require_token)])
async def get_trade_detail(trade_id: int):
    trade = db.get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    exits = db.get_exits_for_trade(trade_id)
    return {
        "trade": serialize_trade(trade),
        "exits": [serialize_exit(e) for e in exits],
    }


@router.get("/{trade_id}/source", response_model=TradeSource, dependencies=[Depends(require_token)])
async def get_trade_source(trade_id: int):
    """The trade plus the signal and raw channel message that produced it."""
    source = db.get_trade_source(trade_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {
        "trade": serialize_trade(source["trade"]),
        "signal": serialize_signal(source["signal"]) if source["signal"] else None,
        "message": serialize_channel_message(source["message"]) if source["message"] else None,
    }
