"""
GET  /api/positions             — open trades (PENDING + ACTIVE) with live unrealized P&L.
POST /api/positions/{id}/close  — manually close an ACTIVE position now.
POST /api/positions/{id}/cancel — manually cancel a PENDING position that never triggered.
"""
from fastapi import APIRouter, Depends, HTTPException

import database as db
from api.auth import require_token
from api.runtime import Runtime, get_runtime
from api.schemas import TradeOut
from api.serializers import serialize_trade

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("", response_model=list[TradeOut], dependencies=[Depends(require_token)])
async def list_positions():
    rows = db.get_open_trades()
    return [serialize_trade(r) for r in rows]


@router.post("/{trade_id}/close", response_model=TradeOut, dependencies=[Depends(require_token)])
async def close_position(trade_id: int, rt: Runtime = Depends(get_runtime)):
    if rt.trade_manager is None:
        raise HTTPException(status_code=503, detail="Trade manager not available")
    try:
        trade = await rt.trade_manager.manual_close(trade_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return serialize_trade(trade)


@router.post("/{trade_id}/cancel", response_model=TradeOut, dependencies=[Depends(require_token)])
async def cancel_position(trade_id: int, rt: Runtime = Depends(get_runtime)):
    if rt.trade_manager is None:
        raise HTTPException(status_code=503, detail="Trade manager not available")
    try:
        trade = await rt.trade_manager.manual_cancel(trade_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return serialize_trade(trade)
