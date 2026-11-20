"""
FastAPI app factory for the embedded dashboard API.

Isolation from the trading loop:
  - Every route is plain async I/O against SQLite or in-memory Runtime state;
    anything that calls the broker goes through asyncio.to_thread (added
    starting Phase 1/2, once such routes exist).
  - A global exception handler turns any unhandled error into a typed 500
    envelope instead of propagating -- a bug in a dashboard route must never
    be able to reach, let alone crash, the bot's own tasks.
  - main.py runs the uvicorn server as its own supervised asyncio task (see
    run_dashboard_api below) so a server-level failure can be restarted
    independently of the monitor/listener/watchdog tasks.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from api.routers import analytics as analytics_router
from api.routers import auth as auth_router
from api.routers import bot as bot_router
from api.routers import instruments as instruments_router
from api.routers import market as market_router
from api.routers import overview as overview_router
from api.routers import positions as positions_router
from api.routers import signals as signals_router
from api.routers import trades as trades_router
from api.routers import ws as ws_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="Signal Bot Dashboard API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )

    app.include_router(bot_router.router)
    app.include_router(auth_router.router)
    app.include_router(ws_router.router)
    app.include_router(overview_router.router)
    app.include_router(positions_router.router)
    app.include_router(trades_router.router)
    app.include_router(signals_router.router)
    app.include_router(analytics_router.router)
    app.include_router(instruments_router.router)
    app.include_router(market_router.router)

    return app


app = create_app()


async def run_dashboard_api():
    """
    Run uvicorn as a coroutine inside the bot's own event loop.

    `loop="none"` tells uvicorn not to install/replace the asyncio event
    loop policy -- it must share the loop main.py already created for the
    Telegram listener and the trade monitor, not spin up its own.
    """
    import uvicorn

    server_config = uvicorn.Config(
        app,
        host=config.DASHBOARD_API_HOST,
        port=config.DASHBOARD_API_PORT,
        loop="none",
        log_level="warning",  # the bot's own logging.basicConfig already covers format/handlers
    )
    server = uvicorn.Server(server_config)
    logger.info(f"Dashboard API starting on http://{config.DASHBOARD_API_HOST}:{config.DASHBOARD_API_PORT}")
    await server.serve()
