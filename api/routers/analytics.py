"""GET /api/analytics — realized P&L breakdown over closed trades, filtered by date range/mode/symbol."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

import database as db
from api.auth import require_token
from api.schemas import AnalyticsResponse

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsResponse, dependencies=[Depends(require_token)])
async def analytics(
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    mode: Optional[str] = Query(default=None, description="paper | live"),
    symbol: Optional[str] = Query(default=None),
):
    return db.get_analytics(date_from=date_from, date_to=date_to, mode=mode, symbol=symbol)
