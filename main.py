"""
Entry point.

Starts:
  - Angel One broker (login once)
  - Database (init schema)
  - Trade manager (price-monitor loop)
  - Telegram listener (signal inflow)
  - Telegram notifier (status outflow)

All coroutines run in a single asyncio event loop.

Usage:
    python main.py              # Run continuously
    python main.py --test       # Parse a sample signal and exit
    python main.py --stats      # Print today's stats and exit
"""
import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime

from colorama import Fore, Style, init as colorama_init

import config
import database as db
from angel_broker import AngelBroker
from trade_manager import TradeManager
from telegram_listener import TelegramListener
from notifier import TelegramNotifier

from api.app import run_dashboard_api
from api.market_data import MarketDataService
from api.runtime import runtime as api_runtime

logger = logging.getLogger(__name__)


def setup_logging():
    colorama_init()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-20s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_PATH),
        ],
    )


async def _supervised_dashboard_api():
    """
    Run the dashboard API forever, restarting it on crash.

    A bug in a dashboard route is isolated per-request by FastAPI's own
    exception handler (see api/app.py); this loop guards against the server
    *itself* dying (e.g. the port already in use, or an error inside
    uvicorn's own serve loop) without that taking down the trading tasks
    running alongside it.
    """
    backoff = 2
    while True:
        try:
            await run_dashboard_api()
            logger.warning("Dashboard API server exited; restarting…")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"Dashboard API crashed, restarting in {backoff}s: {e}")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


def print_banner():
    mode_color = Fore.YELLOW if config.TRADING_MODE == "paper" else Fore.RED
    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════╗
║         📈  TELEGRAM TRADING SIGNAL AUTOMATION          ║
╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}
  Mode: {mode_color}{config.TRADING_MODE.upper()}{Style.RESET_ALL}
  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""")
    print(config.summary())


async def run():
    print_banner()

    # --- Init DB ---
    db.init_db()

    # --- Login to broker ---
    broker = AngelBroker()
    broker.login()

    # --- Listener & notifier share one Telegram client ---
    listener = TelegramListener(on_signal=None)   # callbacks wired below
    notifier = TelegramNotifier(listener.client)

    # --- Trade manager wires everything together ---
    manager = TradeManager(broker=broker, notifier=notifier.send)
    listener.on_signal = manager.on_signal
    listener.on_targets = manager.on_targets

    # --- Dashboard API: read access to the live objects above, nothing more ---
    api_runtime.broker = broker
    api_runtime.trade_manager = manager
    api_runtime.listener = listener
    api_runtime.market_data = MarketDataService(api_runtime)

    # --- Connect Telegram BEFORE sending anything through it ---
    n_channels = await listener.connect()
    if not n_channels:
        print("No channels could be resolved. Check TELEGRAM_SIGNAL_CHANNELS in .env "
              "(a channel ID from a web.telegram.org URL needs the -100 prefix), "
              "then run:  python watch_channel.py --list")
        await listener.stop()
        broker.logout()
        return

    await notifier.send(
        f"🚀 Trading bot online\n"
        f"Mode: {config.TRADING_MODE.upper()}\n"
        f"Channels: {', '.join(str(c) for c in config.TELEGRAM_SIGNAL_CHANNELS)}"
    )

    # No catch-up: a restart should only act on signals that arrive from
    # this point forward. Anything posted while the bot was offline is
    # treated as missed on purpose -- it is not replayed or re-opened.

    # --- Start price monitor + Telegram listener + dashboard API in parallel ---
    monitor_task = asyncio.create_task(manager.start_monitor(), name="monitor")
    listener_task = asyncio.create_task(listener.run(), name="listener")
    watchdog_task = asyncio.create_task(listener.watchdog(), name="telegram_watchdog")
    api_task = asyncio.create_task(_supervised_dashboard_api(), name="dashboard_api")

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _on_signal(*_):
        print("\nShutting down…")
        manager.stop_monitor()
        stop_event.set()

    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _on_signal)
        except NotImplementedError:
            pass

    done, pending = await asyncio.wait(
        {monitor_task, listener_task, watchdog_task, api_task, asyncio.create_task(stop_event.wait())},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()

    await listener.stop()
    broker.logout()
    print("Shutdown complete.")


def cmd_test():
    """Parse the sample signal and print the result."""
    from signal_parser import parse_signal
    sample = """
    CRUDEOIL 17 NOV  8050 CE

    ABOVE :- 120

    STOPLOSS :- 90

    Target 135/150
    """
    sig = parse_signal(sample)
    print("Parsed:")
    print(sig.human_summary)
    print(f"Tradingsymbol: {sig.tradingsymbol}")


def cmd_stats():
    db.init_db()
    stats = db.get_todays_stats()
    print(f"\n── Today's stats ({datetime.now().date()}) ──")
    print(f"  Total trades: {stats.get('total', 0)}")
    print(f"  Wins:         {stats.get('wins', 0)}")
    print(f"  Losses:       {stats.get('losses', 0)}")
    print(f"  Total P&L:    ₹{stats.get('total_pnl', 0):+,.2f}")

    open_trades = db.get_open_trades()
    if open_trades:
        print(f"\n── Open positions ({len(open_trades)}) ──")
        for t in open_trades:
            print(f"  #{t['id']}  {t['status']:<8} {t['tradingsymbol']}  "
                  f"trigger={t['entry_trigger']}  SL={t['stoploss']}")


def main():
    parser = argparse.ArgumentParser(description="Telegram trading signal automation")
    parser.add_argument("--test", action="store_true", help="Parse sample signal and exit")
    parser.add_argument("--stats", action="store_true", help="Show today's stats and exit")
    args = parser.parse_args()

    setup_logging()

    if args.test:
        cmd_test()
        return
    if args.stats:
        cmd_stats()
        return

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nInterrupted.")


if __name__ == "__main__":
    main()
