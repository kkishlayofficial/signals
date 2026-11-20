"""
Dashboard API — embedded inside the bot's own asyncio loop (see main.py).

This package must never:
  - open a second Angel One session (there is exactly one, owned by the bot)
  - call a broker method directly from a request handler without
    `asyncio.to_thread` (every SmartApi call is blocking HTTP)
  - let an unhandled exception here crash the bot's trading tasks

Phase 0 contents: EventBus, bearer-token auth, the Runtime holder that gives
API routes read access to the bot's live objects, and /api/bot/status + /ws.
"""
