"""GET /api/instruments, GET /api/instruments/{exchange}/{token} -- search and detail."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import require_token
from api.runtime import Runtime, get_runtime
from api.schemas import InstrumentOut

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut], dependencies=[Depends(require_token)])
async def search_instruments(
    q: str = Query(..., min_length=1),
    exchange: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    rt: Runtime = Depends(get_runtime),
):
    if rt.market_data is None:
        raise HTTPException(status_code=503, detail="Market data service not ready")
    return await rt.market_data.search_instruments(q, exchange, limit)


@router.get("/{exchange}/{token}", response_model=InstrumentOut, dependencies=[Depends(require_token)])
async def get_instrument(exchange: str, token: str, rt: Runtime = Depends(get_runtime)):
    if rt.market_data is None:
        raise HTTPException(status_code=503, detail="Market data service not ready")
    inst = await rt.market_data.get_instrument(exchange.upper(), token)
    if inst is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return inst
