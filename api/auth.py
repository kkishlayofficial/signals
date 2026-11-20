"""
Auth for the dashboard API.

Two mechanisms:
  - Bearer token on every REST request (Authorization: Bearer <token>),
    checked with constant-time comparison.
  - Single-use WS tickets: the long-lived DASHBOARD_API_TOKEN never has to
    reach the browser's query string (which would land in server logs and
    browser history). The Next.js server holds the real token and exchanges
    it for a 60-second, single-use ticket that the browser puts on the WS URL.
"""
import logging
import secrets
import time
from typing import Dict, Optional

from fastapi import Header, HTTPException, Query, status

import config

logger = logging.getLogger(__name__)

TICKET_TTL_SECONDS = 60

# ticket -> expiry epoch seconds. Small and short-lived; a plain dict is fine
# (this process is the only consumer, no persistence needed across restarts).
_tickets: Dict[str, float] = {}


def _constant_time_eq(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


def require_token(authorization: Optional[str] = Header(default=None)) -> None:
    """FastAPI dependency: raises 401 unless Authorization: Bearer <token> matches."""
    configured = config.DASHBOARD_API_TOKEN
    if not configured:
        # Fail closed. An unset token must never mean "open to everyone".
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DASHBOARD_API_TOKEN is not configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    supplied = authorization[len("Bearer "):]
    if not _constant_time_eq(supplied, configured):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def mint_ws_ticket() -> str:
    """Create a single-use ticket. Call this from an already-authenticated context."""
    _prune_expired()
    ticket = secrets.token_urlsafe(24)
    _tickets[ticket] = time.time() + TICKET_TTL_SECONDS
    return ticket


def consume_ws_ticket(ticket: Optional[str] = Query(default=None)) -> None:
    """FastAPI dependency for a plain HTTP route. Raises 401 on a missing/expired/reused ticket."""
    if not try_consume_ws_ticket(ticket):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired ws ticket")


def try_consume_ws_ticket(ticket: Optional[str]) -> bool:
    """
    Non-raising version for the WebSocket route, where an HTTPException raised
    *before* `accept()` doesn't produce a clean close -- the handler validates
    this itself and closes with a specific code instead.
    """
    _prune_expired()
    if not ticket:
        return False
    expiry = _tickets.pop(ticket, None)  # single-use: pop, don't peek
    if expiry is None or expiry < time.time():
        return False
    return True


def _prune_expired() -> None:
    now = time.time()
    expired = [t for t, exp in _tickets.items() if exp < now]
    for t in expired:
        _tickets.pop(t, None)
