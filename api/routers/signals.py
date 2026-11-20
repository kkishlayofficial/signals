"""GET /api/signals, GET /api/signals/{id} — Telegram signal inflow, paginated + filtered."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import database as db
from api.auth import require_token
from api.schemas import PaginatedSignals, SignalOut
from api.serializers import serialize_signal

router = APIRouter(prefix="/api/signals", tags=["signals"])

# Mirrors the `signals.status` column comment in database.py.
_VALID_STATUS = {
    "RECEIVED", "PARSED", "VALIDATED", "EXECUTED", "CLOSED",
    "REJECTED", "DUPLICATE", "INVALID", "CANCELLED",
}


@router.get("", response_model=PaginatedSignals, dependencies=[Depends(require_token)])
async def list_signals(
    status: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
):
    if status and status.upper() not in _VALID_STATUS:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUS)}")

    result = db.list_signals(status=status, date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    return {
        "items": [serialize_signal(r) for r in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }


@router.get("/{signal_id}", response_model=SignalOut, dependencies=[Depends(require_token)])
async def get_signal_detail(signal_id: int):
    row = db.get_signal(signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return serialize_signal(row)
