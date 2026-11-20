"""POST /api/auth/ws-ticket — mint a 60s single-use ticket for the WS route.

Called by the Next.js server (which holds the real bearer token) so the
long-lived token never has to appear in a browser-visible WS URL.
"""
from fastapi import APIRouter, Depends

from api.auth import mint_ws_ticket, require_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/ws-ticket", dependencies=[Depends(require_token)])
async def issue_ws_ticket():
    return {"ticket": mint_ws_ticket(), "expires_in": 60}
