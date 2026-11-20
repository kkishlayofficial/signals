"""
Trade manager — the heart of the system.

Responsibilities:
  1. Convert ParsedSignal → trade record in DB (PENDING).
  2. Run a background loop that polls LTPs for pending/active trades.
  3. On trigger hit: enter (paper → simulate; live → place real order).
  4. On SL / target hit: exit and record P&L.
  5. Fire notifications on each state transition.

Mode (paper vs live) is read from config.TRADING_MODE.
Switching from paper to live is a single-line change in the .env file.
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Awaitable

import config
import database as db
import paper_trading
from signal_parser import ParsedSignal, MONTHS

from api.runtime import runtime as api_runtime

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str], Awaitable[None]]

# How many times a failing entry/exit order is retried before the bot stops
# trying and asks for manual intervention.
MAX_ORDER_ATTEMPTS = 3

# _classify_activity's category -> bot_events.level. The category itself
# (ENTERED/EXITED/CANCELLED/SKIPPED/ERROR/INFO) is kept too, for finer display
# than the coarse level alone gives.
_CATEGORY_TO_LEVEL = {
    "ENTERED": "INFO",
    "EXITED": "INFO",
    "CANCELLED": "WARNING",
    "SKIPPED": "WARNING",
    "ERROR": "ERROR",
    "INFO": "INFO",
}


def _classify_activity(msg: str) -> str:
    """
    Every notify() call already reads as a human sentence describing one
    lifecycle event -- this just buckets it for the dashboard's activity
    log instead of requiring a tag at every one of the ~20 call sites.
    """
    low = msg.lower()
    if "p&l:" in low:
        return "EXITED"
    if "✅ entered" in low:
        return "ENTERED"
    if "🗑" in msg or "cancelled" in low:
        return "CANCELLED"
    if "skipping" in low or "duplicate ignored" in low:
        return "SKIPPED"
    if "❌" in msg or "🚨" in msg:
        return "ERROR"
    return "INFO"


class TradeManager:
    def __init__(self, broker, notifier: Optional[NotifyFn] = None):
        """
        broker: an AngelBroker instance (always required — used for LTP quotes
                even in paper mode).
        notifier: async callable (str) -> None, called on every event.
        """
        self.live_broker = broker
        self.paper = paper_trading.PaperBroker(live_broker=broker)
        self.notifier = notifier
        self.mode = config.TRADING_MODE
        self._poll_task: Optional[asyncio.Task] = None
        self._stop = False
        # Order attempts per trade ID. A broker call that raises may still have
        # reached the exchange (e.g. a timeout after the order was accepted),
        # so the polling loop must not retry it forever -- that is how you end
        # up with five entries for one signal.
        self._entry_attempts: Dict[int, int] = {}
        self._exit_attempts: Dict[int, int] = {}
        self._ticker = None
        self._ws_registry: Dict[str, tuple] = {}
        # Dashboard-controlled pause of NEW signal intake only (see
        # api/routers/bot.py, Phase 5). Already-open positions are never
        # affected by this flag -- the monitor loop below doesn't check it.
        self.paused = False
        # Rate-gate for the dashboard's per-tick PRICE_UPDATE/POSITION_UPDATE/
        # PNL_UPDATE events, keyed by trade id -- ~4/s, matching the plan's
        # own coalescing target. The trading decisions above this are never
        # throttled; only the dashboard's own event stream is.
        self._last_trade_tick_emit: Dict[int, float] = {}

    # ---------------------------------------------------- notifications
    async def notify(self, msg: str):
        logger.info(msg.replace("\n", " | "))
        category = _classify_activity(msg)
        try:
            db.log_activity(category, msg)
        except Exception as e:
            logger.warning(f"Failed to log activity: {e}")
        try:
            db.log_bot_event(_CATEGORY_TO_LEVEL.get(category, "INFO"), category, msg)
        except Exception as e:
            logger.warning(f"Failed to log bot event: {e}")

        if category == "ERROR":
            # Loose heuristic (notify() only has the human-readable string,
            # not a structured source) -- good enough for a rough error
            # count split on /api/bot/status without inventing a richer
            # error-reporting path for Phase 1.
            bucket = "broker" if ("angel" in msg.lower() or "order" in msg.lower()) else (
                "telegram" if "telegram" in msg.lower() else "other")
            api_runtime.errors.record(bucket, msg)

        api_runtime.bus.emit("SYSTEM_LOG", {"message": msg, "category": category})

        if self.notifier:
            try:
                await self.notifier(msg)
            except Exception as e:
                logger.warning(f"Notifier failed: {e}")

    # ---------------------------------------------------- signal in
    def _advance_signal(self, signal_id: Optional[int], status: str, **kwargs):
        """Best-effort signals-table update; signal_id is None when the
        caller (e.g. catch-up, or a direct test call) never recorded one."""
        if signal_id is None:
            return
        try:
            db.update_signal(signal_id, status=status, **kwargs)
        except Exception as e:
            logger.warning(f"Failed to update signal #{signal_id} -> {status}: {e}")

    async def on_signal(self, sig: ParsedSignal, signal_id: Optional[int] = None) -> Optional[int]:
        """
        Register a new signal. Checks capacity, resolves instrument, persists.

        Returns the trade id this signal produced, amended, or (for a
        duplicate) was a repost of -- or None if it was rejected outright.
        `signal_id` is the signals-table row the caller already created for
        this message (see telegram_listener._handle_message); its lifecycle
        status is advanced here as the signal is validated/rejected.
        """
        if self.paused:
            logger.info(f"Paused -- ignoring signal {sig.tradingsymbol}")
            await self.notify(f"⏸️ Paused -- ignoring signal: {sig.tradingsymbol}")
            self._advance_signal(signal_id, "REJECTED", reject_reason="bot paused")
            return None

        # Free up slots held by signals whose trigger never came, BEFORE the
        # capacity check -- otherwise a few untriggered signals permanently
        # wedge the bot at MAX_OPEN_POSITIONS.
        await self._expire_stale()

        # Capacity check (MAX_OPEN_POSITIONS <= 0 means unlimited)
        open_trades = db.get_open_trades()
        if config.MAX_OPEN_POSITIONS > 0 and len(open_trades) >= config.MAX_OPEN_POSITIONS:
            await self.notify(
                f"⚠️ Max open positions ({config.MAX_OPEN_POSITIONS}) reached — "
                f"skipping signal: {sig.tradingsymbol}"
            )
            self._advance_signal(
                signal_id, "REJECTED",
                reject_reason=f"max open positions ({config.MAX_OPEN_POSITIONS}) reached",
            )
            return None

        # Resolve instrument
        try:
            inst = self.live_broker.find_instrument(
                symbol=sig.symbol,
                expiry_day=sig.expiry_day,
                expiry_month=sig.expiry_month,
                expiry_year=sig.expiry_year,
                strike=sig.strike,
                option_type=sig.option_type,
            )
        except Exception as e:
            await self.notify(f"❌ Instrument lookup failed for {sig.tradingsymbol}: {e}")
            self._advance_signal(signal_id, "REJECTED", reject_reason=f"instrument lookup failed: {e}")
            return None

        # Reposted / edited signals arrive as fresh messages. Don't stack a
        # second position on top of the one already working.
        dupe = db.find_open_duplicate(inst["symbol"], sig.action, sig.entry_price)
        if dupe:
            # A quoted follow-up carrying the real targets re-parses as the
            # same signal, because the quote replays the original text. That
            # is an amendment, not a repost: take the targets off it.
            if (sig.targets_explicit and dupe.get("targets_provisional")
                    and sig.targets != dupe["targets"]):
                if db.update_targets(dupe["id"], sig.targets):
                    await self.notify(
                        f"🎯 Targets updated on #{dupe['id']} {dupe['tradingsymbol']}\n"
                        f"   {dupe['targets']} → {sig.targets}"
                        f"  (previous ones were a 1.5R placeholder)"
                    )
                    api_runtime.bus.emit("TRADE_UPDATED", {
                        "trade_id": dupe["id"], "symbol": dupe["tradingsymbol"],
                        "targets": sig.targets,
                    })
                    self._advance_signal(signal_id, "VALIDATED", trade_id=dupe["id"])
                    return dupe["id"]
            await self.notify(
                f"🔁 Duplicate ignored: {inst['symbol']} {sig.action} "
                f"@ {sig.entry_price} is already open as #{dupe['id']} "
                f"({dupe['status']})"
            )
            self._advance_signal(
                signal_id, "DUPLICATE",
                reject_reason=f"duplicate of open trade #{dupe['id']}", trade_id=dupe["id"],
            )
            return dupe["id"]

        # Capital cap. MAX_CAPITAL_PER_TRADE was read from .env and printed in
        # the startup banner but never actually checked against anything.
        qty = config.DEFAULT_QUANTITY * inst["lotsize"]
        # NOTE: for a BUY this is the premium paid, which is the real outlay.
        # For writing an option (SELL) the premium is a credit and the actual
        # margin blocked is far larger, so this cap under-estimates a short.
        est_cost = sig.entry_price * qty
        if config.MAX_CAPITAL_PER_TRADE > 0 and est_cost > config.MAX_CAPITAL_PER_TRADE:
            await self.notify(
                f"⚠️ Skipping {inst['symbol']} — needs ₹{est_cost:,.0f} "
                f"({qty} × ₹{sig.entry_price}) but MAX_CAPITAL_PER_TRADE is "
                f"₹{config.MAX_CAPITAL_PER_TRADE:,.0f}.\n"
                f"   Raise the cap in .env, or lower DEFAULT_QUANTITY."
            )
            self._advance_signal(
                signal_id, "REJECTED",
                reject_reason=f"capital cap exceeded: needs ₹{est_cost:,.0f}, "
                              f"cap ₹{config.MAX_CAPITAL_PER_TRADE:,.0f}",
            )
            return None

        # Signals are only good for a narrow window. Decide right now, off a
        # fresh quote, instead of parking the trade as "waiting for trigger":
        #   - price hasn't reached the trigger yet -> that's an equal-or-better
        #     price than the one the channel called out, so enter immediately
        #     at the current market price rather than waiting for it to climb
        #     (ABOVE) or fall (BELOW) to the exact level.
        #   - price has already passed the trigger -> the window the signal
        #     was good for is gone; chasing it now is a different trade with
        #     different risk, so the signal is discarded, not queued.
        try:
            ltp = self.live_broker.get_ltp(inst["exch_seg"], inst["symbol"], inst["token"])
        except Exception as e:
            await self.notify(f"❌ Could not fetch price for {inst['symbol']}: {e}")
            self._advance_signal(signal_id, "REJECTED", reject_reason=f"ltp fetch failed: {e}")
            return None

        # A small overshoot past the trigger is still the same entry window --
        # only discard once price has moved more than the tolerance beyond it.
        tolerance = config.ENTRY_STALE_TOLERANCE_POINTS
        if sig.entry_condition == "ABOVE":
            already_past = ltp > sig.entry_price + tolerance
        else:
            already_past = ltp < sig.entry_price - tolerance
        if already_past:
            await self.notify(
                f"🗑 Stale signal discarded: {inst['symbol']} {sig.action} "
                f"{sig.entry_condition} {sig.entry_price} — price is already "
                f"₹{ltp:.2f}, past the entry window. Not chasing it."
            )
            self._advance_signal(
                signal_id, "REJECTED",
                reject_reason=(
                    f"stale: price {ltp} already past trigger {sig.entry_price} "
                    f"({sig.entry_condition})"
                ),
            )
            return None

        month_abbr = list(MONTHS.keys())[sig.expiry_month - 1]
        expiry_str = f"{sig.expiry_day:02d}-{month_abbr}-{sig.expiry_year}"

        trade_record = {
            "mode": self.mode,
            "symbol": sig.symbol,
            "tradingsymbol": inst["symbol"],
            "exchange": inst["exch_seg"],
            "option_type": sig.option_type,
            "strike": sig.strike,
            "expiry": expiry_str,
            "action": sig.action,
            "quantity": config.DEFAULT_QUANTITY,
            "lot_size": inst["lotsize"],
            "entry_condition": sig.entry_condition,
            "entry_trigger": sig.entry_price,
            "stoploss": sig.stoploss,
            "targets": sig.targets,
            "raw_signal": sig.raw_text,
            "targets_provisional": not sig.targets_explicit,
            "instrument_token": inst["token"],
            "instrument_ticksize": inst.get("ticksize"),
            "signal_id": signal_id,
        }

        trade_id = db.insert_trade(trade_record)
        self._advance_signal(signal_id, "VALIDATED", trade_id=trade_id)
        api_runtime.mark_signal()

        # Subscribe to real-time ticks so the position is tracked from the
        # moment it opens, with no gap waiting for the next poll cycle.
        new_trade = db.get_trade(trade_id)
        if new_trade:
            self._ws_subscribe_trade(new_trade, inst)

        mode_tag = "📝 PAPER" if self.mode == "paper" else "💰 LIVE"
        tgt_note = ("" if sig.targets_explicit else
                    "\n⚠️ No target in the message — using a 1.5R placeholder. "
                    "It will be replaced if the channel posts the real one.")
        await self.notify(
            f"{mode_tag}  Signal registered #{trade_id}\n"
            f"{sig.human_summary}\n"
            f"Lot size: {inst['lotsize']}, Qty: {config.DEFAULT_QUANTITY} lot(s)"
            f"{tgt_note}"
        )

        if new_trade is None:
            return trade_id
        await self._execute_entry(new_trade, ltp, inst["token"], inst.get("ticksize") or 0.05)
        return trade_id

    # ---------------------------------------------------- targets follow-up
    async def on_targets(self, targets: List[float], quoted_text: Optional[str] = None):
        """
        Apply a target-only message to the trade it belongs to.

        Channels post the call first and the target second, as a reply quoting
        it. That reply's own text is just "Target 135/150" -- no instrument, no
        stoploss -- so it can never parse as a signal. Without this the trade
        would run to the invented 1.5R placeholder instead of the real target.

        `quoted_text` is the text of the message being replied to, when there
        is one; it identifies the trade exactly. Otherwise the most recent open
        trade still on a placeholder gets the targets.
        """
        trade = None
        if quoted_text:
            trade = db.find_by_raw_signal(quoted_text)
        if trade is None:
            trade = db.get_latest_awaiting_targets()

        if trade is None:
            logger.info(f"Target message {targets} matched no open trade; ignoring")
            return

        if not trade.get("targets_provisional"):
            logger.info(f"Trade #{trade['id']} already has real targets "
                        f"{trade['targets']}; ignoring follow-up {targets}")
            return

        # The targets have to make sense against the entry we actually took.
        entry = trade.get("entry_price") or trade["entry_trigger"]
        if trade["action"] == "BUY":
            good = [t for t in targets if t > entry]
        else:
            good = [t for t in targets if t < entry]

        if not good:
            await self.notify(
                f"⚠️ Ignoring targets {targets} for #{trade['id']} "
                f"{trade['tradingsymbol']} — all on the losing side of "
                f"entry {entry}."
            )
            return

        good.sort(reverse=(trade["action"] == "SELL"))
        if good == trade["targets"]:
            return

        if db.update_targets(trade["id"], good):
            await self.notify(
                f"🎯 Targets updated on #{trade['id']} {trade['tradingsymbol']}\n"
                f"   {trade['targets']} → {good}"
                + ("  (previous ones were a 1.5R placeholder)"
                   if trade.get("targets_provisional") else "")
            )
            api_runtime.bus.emit("TRADE_UPDATED", {
                "trade_id": trade["id"], "symbol": trade["tradingsymbol"], "targets": good,
            })

    # ---------------------------------------------------- housekeeping
    async def _expire_stale(self):
        """Cancel PENDING signals that never triggered, and tell the user."""
        try:
            cancelled = db.expire_stale_pending(config.PENDING_TTL_HOURS)
        except Exception as e:
            logger.warning(f"Stale-pending sweep failed: {e}")
            return

        for t in cancelled:
            self._entry_attempts.pop(t["id"], None)
            await self.notify(
                f"🗑 Cancelled #{t['id']} {t['tradingsymbol']} — {t['notes']}"
            )
            if t.get("signal_id"):
                self._advance_signal(t["signal_id"], "CANCELLED", reject_reason=t.get("notes"))

    # ------------------------------------------------------- dashboard actions
    async def manual_cancel(self, trade_id: int) -> Dict[str, Any]:
        """Cancel a PENDING trade on demand, from the dashboard."""
        trade = db.get_trade(trade_id)
        if trade is None:
            raise ValueError(f"Trade #{trade_id} not found")
        if trade["status"] != "PENDING":
            raise ValueError(f"Trade #{trade_id} is {trade['status']}, not PENDING")

        db.mark_cancelled(trade_id, "Manually cancelled")
        self._entry_attempts.pop(trade_id, None)
        if trade.get("signal_id"):
            self._advance_signal(trade["signal_id"], "CANCELLED", reject_reason="Manually cancelled")
        await self.notify(f"🗑 Cancelled #{trade_id} {trade['tradingsymbol']} — Manually cancelled")
        return db.get_trade(trade_id)

    async def manual_close(self, trade_id: int) -> Dict[str, Any]:
        """
        Close an ACTIVE position on demand, from the dashboard.

        Exits at the trade's last-polled LTP (refreshed every monitor tick)
        rather than fetching a fresh quote here -- that keeps this request
        handler from making a blocking broker call of its own, and reuses
        the exact same entry/exit machinery (_exit_trade) a stoploss or
        target hit would use, so live mode still places a real closing
        order.
        """
        trade = db.get_trade(trade_id)
        if trade is None:
            raise ValueError(f"Trade #{trade_id} not found")
        if trade["status"] != "ACTIVE":
            raise ValueError(f"Trade #{trade_id} is {trade['status']}, not ACTIVE")

        token = trade.get("instrument_token")
        if not token:
            raise ValueError(f"Trade #{trade_id} has no resolved instrument token; cannot close")
        ltp = trade.get("current_ltp") or trade.get("entry_price")
        if ltp is None:
            raise ValueError(f"Trade #{trade_id} has no price yet; try again shortly")

        await self._exit_trade(trade, ltp, token, "MANUAL")
        return db.get_trade(trade_id)

    async def _await_fill(self, order_id: str, fallback: float) -> float:
        """
        The price an order actually filled at, read from the order book.

        The old code used the last polled LTP as the fill price for both entry
        and exit, so every recorded P&L was a guess that ignored slippage.
        Falls back to the LTP if the order book can't confirm in time.
        """
        deadline = asyncio.get_running_loop().time() + config.ORDER_FILL_TIMEOUT
        last = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                last = self.live_broker.order_state(order_id)
            except Exception as e:
                logger.warning(f"Order-state lookup failed for {order_id}: {e}")
                break

            if last["state"] == "filled" and last["avg_price"]:
                return last["avg_price"]
            if last["state"] == "dead":
                raise RuntimeError(
                    f"order {order_id} ended as '{last['status']}' without filling")
            await asyncio.sleep(1)

        logger.warning(
            f"Could not confirm fill price for {order_id} "
            f"(last state: {last}); using LTP {fallback}")
        return fallback

    async def _place_exchange_stop(self, trade: Dict[str, Any], token: str,
                                   ticksize: float) -> Optional[str]:
        """
        Put a real STOPLOSS_LIMIT order at the exchange, so the position is
        protected even if this process dies, the laptop sleeps, or price gaps
        between two 5-second polls. Returns the order ID, or None on failure.
        """
        qty = trade["quantity"] * trade["lot_size"]
        stop_action = "SELL" if trade["action"] == "BUY" else "BUY"
        trigger = trade["stoploss"]

        # The limit has to sit on the far side of the trigger or a fast move
        # blows straight through it and nothing fills.
        buffer = trigger * (config.SL_LIMIT_BUFFER_PCT / 100.0)
        limit = trigger - buffer if stop_action == "SELL" else trigger + buffer

        try:
            sl_id = self.live_broker.place_sl_order(
                tradingsymbol=trade["tradingsymbol"],
                token=token,
                exchange=trade["exchange"],
                action=stop_action,
                quantity=qty,
                trigger_price=trigger,
                limit_price=max(limit, 0.05),
                ticksize=ticksize,
            )
            db.set_sl_order(trade["id"], sl_id)
            return sl_id
        except Exception as e:
            await self.notify(
                f"⚠️ Could not place the protective stoploss for "
                f"#{trade['id']} {trade['tradingsymbol']}: {e}\n"
                f"   The position is open with NO stop at the exchange. "
                f"The software stop is still watching, but it only works "
                f"while this script runs."
            )
            return None

    async def _cancel_exchange_stop(self, trade: Dict[str, Any]) -> str:
        """
        Cancel the resting stoploss before closing a position by hand.

        Skipping this is how you end up accidentally reversed: the target exit
        sells your long, then the untouched stop order sells it again and you
        are short a contract you never meant to write.

        Returns "cancelled", "already_filled", or "failed".
        """
        sl_id = trade.get("sl_order_id")
        if not sl_id:
            return "cancelled"

        try:
            state = self.live_broker.order_state(sl_id)
            if state["state"] == "filled":
                return "already_filled"
            if state["state"] == "dead":
                db.set_sl_order(trade["id"], None)
                return "cancelled"
        except Exception as e:
            logger.warning(f"Could not read stop state for {sl_id}: {e}")

        try:
            self.live_broker.cancel_order(sl_id, variety="STOPLOSS")
            db.set_sl_order(trade["id"], None)
            return "cancelled"
        except Exception as e:
            await self.notify(
                f"🚨 Could not cancel the resting stoploss {sl_id} for "
                f"#{trade['id']}: {e}\n"
                f"   NOT closing on target, to avoid ending up with a "
                f"reversed position. Check the Angel One order book."
            )
            return "failed"

    # ---------------------------------------------------- price monitor
    async def start_monitor(self):
        """
        Start the price monitor.

        Tries to open a WebSocket stream for real-time ticks.  If that
        works, ticks are processed instantly as they arrive.  A slower
        polling loop runs alongside as a fallback — it catches anything
        the WebSocket missed (new instruments, reconnect gaps) and runs
        the stale-pending sweep.
        """
        self._stop = False
        self._loop = asyncio.get_running_loop()
        self._tick_queue: asyncio.Queue = asyncio.Queue()
        # token → (instrument_dict, {trade_id, ...})
        self._ws_registry: Dict[str, tuple] = {}

        # Try to start the WebSocket ticker
        self._ticker = None
        try:
            self._ticker = self.live_broker.create_ticker(self._on_ws_tick_threadsafe)
            self._ticker.start()
            logger.info("Real-time WebSocket ticker started.")
        except Exception as e:
            logger.warning(f"WebSocket ticker unavailable, using polling only: {e}")

        # Process the tick queue in the async loop
        ws_task = asyncio.create_task(self._process_tick_queue(), name="ws-ticks")

        logger.info(f"Starting price monitor (WS {'active' if self._ticker else 'off'})")
        while not self._stop:
            try:
                await self._tick()
            except Exception as e:
                logger.exception(f"Monitor tick error: {e}")
            # Use fast polling when WebSocket is not actually connected
            ws_live = self._ticker and self._ticker._running
            await asyncio.sleep(30.0 if ws_live else config.PRICE_POLL_INTERVAL)

        ws_task.cancel()
        if self._ticker:
            self._ticker.stop()

    def stop_monitor(self):
        self._stop = True

    # -- WebSocket tick handling --

    def _on_ws_tick_threadsafe(self, token: str, ltp: float):
        """Called from the WebSocket thread; enqueue for the async loop."""
        try:
            self._loop.call_soon_threadsafe(self._tick_queue.put_nowait, (token, ltp))
        except Exception:
            pass

    async def _process_tick_queue(self):
        """Drain the tick queue and act on each price update immediately."""
        while not self._stop:
            try:
                token, ltp = await asyncio.wait_for(
                    self._tick_queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Forward to the market-data service unconditionally -- it
            # tracks staleness and builds live candles for whatever it's
            # been asked to watch, independent of whether this token is also
            # held by a trade. This never touches trading decisions below.
            if api_runtime.market_data is not None:
                try:
                    api_runtime.market_data.on_tick(token, ltp)
                except Exception as e:
                    logger.debug(f"market_data.on_tick failed for {token}: {e}")

            reg = self._ws_registry.get(token)
            if not reg:
                continue
            inst, trade_ids = reg
            ticksize = inst.get("ticksize") or 0.05
            api_runtime.mark_tick()

            for tid in list(trade_ids):
                trade = db.get_trade(tid)
                if not trade or trade["status"] not in ("PENDING", "ACTIVE"):
                    trade_ids.discard(tid)
                    continue
                try:
                    db.update_ltp(tid, ltp)
                    self._emit_tick_events(trade, ltp)
                    if trade["status"] == "PENDING":
                        await self._check_pending(trade, ltp, inst["token"], ticksize)
                    elif trade["status"] == "ACTIVE":
                        await self._check_active(trade, ltp, inst["token"], ticksize)
                except Exception as e:
                    logger.warning(f"WS tick processing error for #{tid}: {e}")

    def _emit_tick_events(self, trade: Dict[str, Any], ltp: float):
        """
        PRICE_UPDATE/POSITION_UPDATE/PNL_UPDATE for the dashboard, rate-gated
        to ~4/s per trade. Purely cosmetic/informational -- never gates or
        delays the trigger/SL/target checks that run alongside it.
        """
        now = time.monotonic()
        last = self._last_trade_tick_emit.get(trade["id"], 0)
        if now - last < 0.25:
            return
        self._last_trade_tick_emit[trade["id"]] = now

        api_runtime.bus.emit("PRICE_UPDATE", {
            "trade_id": trade["id"], "symbol": trade["tradingsymbol"], "ltp": ltp,
        })
        if trade["status"] == "ACTIVE":
            try:
                unrealized = paper_trading.calculate_pnl(trade, ltp)
            except Exception:
                unrealized = None
            api_runtime.bus.emit("POSITION_UPDATE", {
                "trade_id": trade["id"], "symbol": trade["tradingsymbol"], "ltp": ltp,
            })
            api_runtime.bus.emit("PNL_UPDATE", {
                "trade_id": trade["id"], "symbol": trade["tradingsymbol"],
                "unrealized_pnl": unrealized,
            })

    def _ws_subscribe_trade(self, trade: Dict[str, Any], inst: Dict[str, Any]):
        """Register a trade for real-time tick processing."""
        if not self._ticker:
            return
        token = inst["token"]
        if token in self._ws_registry:
            self._ws_registry[token][1].add(trade["id"])
        else:
            self._ws_registry[token] = (inst, {trade["id"]})
        self._ticker.subscribe(trade["exchange"], token)

    async def _tick(self):
        """One polling iteration."""
        await self._expire_stale()

        open_trades = db.get_open_trades()
        if not open_trades:
            return

        # One LTP call per instrument per tick. Previously the price and the
        # instrument token shared a Dict[str, float] under mangled keys; they
        # are separate things, so they get separate caches.
        quotes: Dict[str, float] = {}
        instruments: Dict[str, Dict[str, Any]] = {}
        ltp_updates: list = []

        for trade in open_trades:
            key = f"{trade['exchange']}:{trade['tradingsymbol']}"
            if key not in quotes:
                token = trade.get("instrument_token")
                if token:
                    # Fast path: the instrument was resolved once at signal
                    # time (on_signal) and the token persisted alongside the
                    # trade, so this skips re-scanning the 169k-row
                    # instrument master on every single poll cycle.
                    # ticksize only matters for live-mode order rounding;
                    # default to 0.05 (matches angel_broker's own fallback)
                    # if it somehow wasn't captured.
                    inst = {
                        "token": token,
                        "symbol": trade["tradingsymbol"],
                        "exch_seg": trade["exchange"],
                        "lotsize": trade["lot_size"],
                        "ticksize": trade.get("instrument_ticksize") or 0.05,
                    }
                    try:
                        ltp = self.live_broker.get_ltp(trade["exchange"], trade["tradingsymbol"], token)
                    except Exception as e:
                        logger.warning(f"LTP fetch failed for {key}: {e}")
                        continue
                else:
                    # Fallback for trades created before instrument_token
                    # existed on the trades table -- resolve the slow way,
                    # exactly as before.
                    try:
                        inst = self.live_broker.find_instrument(
                            symbol=trade["symbol"],
                            expiry_day=int(trade["expiry"].split("-")[0]),
                            expiry_month=list(MONTHS.keys()).index(trade["expiry"].split("-")[1]) + 1,
                            expiry_year=int(trade["expiry"].split("-")[2]),
                            strike=trade["strike"],
                            option_type=trade["option_type"],
                        )
                        ltp = self.live_broker.get_ltp(
                            trade["exchange"], trade["tradingsymbol"], inst["token"]
                        )
                    except Exception as e:
                        logger.warning(f"LTP fetch failed for {key}: {e}")
                        continue
                quotes[key] = ltp
                instruments[key] = inst
                self._ws_subscribe_trade(trade, inst)

            ltp = quotes.get(key)
            if ltp is None:
                continue
            inst = instruments[key]
            token = inst["token"]
            ticksize = inst.get("ticksize") or 0.05

            ltp_updates.append((trade["id"], ltp))
            self._emit_tick_events(trade, ltp)
            if api_runtime.market_data is not None:
                try:
                    api_runtime.market_data.on_tick(token, ltp)
                except Exception as e:
                    logger.debug(f"market_data.on_tick failed for {token}: {e}")

            if trade["status"] == "PENDING":
                await self._check_pending(trade, ltp, token, ticksize)
            elif trade["status"] == "ACTIVE":
                await self._check_active(trade, ltp, token, ticksize)

        if ltp_updates:
            try:
                db.bulk_update_ltp(ltp_updates)
            except Exception as e:
                logger.debug(f"LTP write-back failed: {e}")
            api_runtime.mark_tick()

    async def _check_pending(self, trade: Dict[str, Any], ltp: float,
                             token: str, ticksize: float = 0.05):
        """
        Fallback path for any trade that is still PENDING by the time the
        monitor loop sees it (e.g. a legacy row, or on_signal's immediate
        entry below didn't run for some reason). Fresh signals no longer
        wait here -- on_signal decides entry-now-or-discard synchronously.
        """
        if not paper_trading.check_trigger_hit(trade, ltp):
            return
        await self._execute_entry(trade, ltp, token, ticksize)

    async def _execute_entry(self, trade: Dict[str, Any], ltp: float,
                             token: str, ticksize: float = 0.05):
        trigger = trade["entry_trigger"]
        qty = trade["quantity"] * trade["lot_size"]
        max_slip_pct = config.MAX_ENTRY_SLIPPAGE_PCT

        # Cap the entry price to limit slippage
        if trade["action"] == "BUY":
            limit_cap = trigger * (1 + max_slip_pct / 100.0)
        else:
            limit_cap = trigger * (1 - max_slip_pct / 100.0)

        use_limit = max_slip_pct > 0 and (
            (trade["action"] == "BUY" and ltp > limit_cap) or
            (trade["action"] == "SELL" and ltp < limit_cap)
        )

        # Trigger fired — enter the trade
        if self.mode == "paper":
            order_id = self.paper.place_market_order(
                trade["tradingsymbol"], token, trade["exchange"],
                trade["action"], qty,
            )
            fill_price = min(ltp, limit_cap) if trade["action"] == "BUY" else max(ltp, limit_cap)
        else:
            attempts = self._entry_attempts.get(trade["id"], 0)
            if attempts >= MAX_ORDER_ATTEMPTS:
                return

            self._entry_attempts[trade["id"]] = attempts + 1
            try:
                if use_limit:
                    order_id = self.live_broker.place_limit_order(
                        tradingsymbol=trade["tradingsymbol"],
                        token=token,
                        exchange=trade["exchange"],
                        action=trade["action"],
                        quantity=qty,
                        limit_price=limit_cap,
                        ticksize=ticksize,
                    )
                else:
                    order_id = self.live_broker.place_market_order(
                        tradingsymbol=trade["tradingsymbol"],
                        token=token,
                        exchange=trade["exchange"],
                        action=trade["action"],
                        quantity=qty,
                    )
                fill_price = await self._await_fill(order_id, fallback=ltp)
            except Exception as e:
                remaining = MAX_ORDER_ATTEMPTS - self._entry_attempts[trade["id"]]
                if remaining > 0:
                    await self.notify(
                        f"❌ Live entry order failed #{trade['id']}: {e}\n"
                        f"   Retrying ({remaining} left)."
                    )
                else:
                    db.mark_cancelled(trade["id"], f"entry order failed: {e}")
                    await self.notify(
                        f"❌ Giving up on #{trade['id']} {trade['tradingsymbol']} "
                        f"after {MAX_ORDER_ATTEMPTS} failed entry attempts.\n"
                        f"   Marked CANCELLED. Check the broker for stray orders."
                    )
                    # A real execution failure, distinct from a RECEIVED
                    # signal never finding capacity/capital -- surfaced under
                    # REJECTED with that reason, since the signal lifecycle
                    # (unlike the trades table) has no separate "execution
                    # failed" terminal state of its own.
                    if trade.get("signal_id"):
                        self._advance_signal(
                            trade["signal_id"], "REJECTED",
                            reject_reason=f"execution failed after {MAX_ORDER_ATTEMPTS} attempts: {e}",
                        )
                return

        db.mark_entered(trade["id"], fill_price, order_id)
        self._entry_attempts.pop(trade["id"], None)
        if trade.get("signal_id"):
            self._advance_signal(trade["signal_id"], "EXECUTED")
        api_runtime.mark_trade()
        api_runtime.bus.emit("TRADE_EXECUTED", {
            "trade_id": trade["id"],
            "symbol": trade["tradingsymbol"],
            "side": trade["action"],
            "entry_price": fill_price,
            "quantity": qty,
            "stop_loss": trade["stoploss"],
            "target": (trade.get("targets") or [None])[0],
        })

        sl_note = ""
        if self.mode == "live" and config.USE_EXCHANGE_STOPLOSS:
            sl_id = await self._place_exchange_stop(trade, token, ticksize)
            sl_note = (f"\n   Stop at exchange: {sl_id} @ ₹{trade['stoploss']}"
                       if sl_id else "\n   ⚠️ NO stop at the exchange")
        elif self.mode == "live":
            sl_note = "\n   ⚠️ Exchange stoploss disabled (USE_EXCHANGE_STOPLOSS=false)"

        slip = fill_price - trade["entry_trigger"]
        order_type = "LIMIT" if use_limit else "MARKET"
        await self.notify(
            f"✅ ENTERED #{trade['id']}  {trade['tradingsymbol']}\n"
            f"   {trade['action']} @ ₹{fill_price:.2f} ({order_type})"
            f" (trigger was {trade['entry_trigger']}, slippage ₹{slip:+.2f})"
            + sl_note
        )

    async def _check_active(self, trade: Dict[str, Any], ltp: float,
                            token: str, ticksize: float = 0.05):
        # Has the exchange already stopped us out? If so the position is
        # ALREADY FLAT, and sending another exit order would open a new
        # position in the opposite direction. Settle the books instead.
        if self.mode == "live" and trade.get("sl_order_id"):
            try:
                state = self.live_broker.order_state(trade["sl_order_id"])
            except Exception as e:
                logger.warning(f"Stop-state check failed for #{trade['id']}: {e}")
                state = None

            if state and state["state"] == "filled":
                await self._settle_exchange_stop(trade, state)
                return
            if state and state["state"] == "dead":
                db.set_sl_order(trade["id"], None)
                await self.notify(
                    f"⚠️ The exchange stop for #{trade['id']} "
                    f"{trade['tradingsymbol']} is gone (status: "
                    f"{state['status']}). Falling back to the software stop; "
                    f"it only protects you while this script is running."
                )

        # SL first (safety)
        if paper_trading.check_stoploss_hit(trade, ltp):
            await self._exit_trade(trade, ltp, token, "STOPLOSS")
            return

        # Trailing stop: move SL up as price moves favorably
        if config.TRAILING_SL_ENABLED:
            already_trailing = trade.get("trailing_sl") is not None

            if already_trailing and paper_trading.check_trailing_sl_hit(trade, ltp):
                await self._exit_trade(trade, ltp, token, "TRAILING_SL")
                return

            # Gate activation on the first target actually being hit, unless
            # that gate is turned off (then trailing arms immediately).
            activation_target = None
            if not already_trailing and config.TRAILING_SL_AFTER_TARGET_ONLY:
                targets = trade.get("targets") or []
                activation_target = targets[0] if targets else None

            new_tsl = paper_trading.compute_trailing_sl(
                trade, ltp, config.TRAILING_SL_PCT, activation_target
            )
            if new_tsl is not None:
                is_buy = trade["action"] == "BUY"
                peak = max(trade.get("peak_ltp") or ltp, ltp) if is_buy else min(trade.get("peak_ltp") or ltp, ltp)
                db.update_trailing_sl(trade["id"], new_tsl, peak)
                old_tsl = trade.get("trailing_sl")
                if old_tsl is None:
                    await self.notify(
                        f"📈 Trailing SL activated #{trade['id']} {trade['tradingsymbol']}\n"
                        f"   TSL: ₹{new_tsl:.2f} (peak: ₹{peak:.2f}, trail: {config.TRAILING_SL_PCT}%)"
                    )

            if already_trailing or new_tsl is not None:
                # Trailing is active (or just activated) -- skip fixed target exits
                return
            # Trailing not activated yet (target not reached) -- fall through
            # to the fixed stoploss/target checks below.

        tgt_idx = paper_trading.check_target_hit(trade, ltp)
        if tgt_idx is not None:
            await self._exit_trade(trade, ltp, token, f"TARGET_{tgt_idx + 1}")

    async def _settle_exchange_stop(self, trade: Dict[str, Any],
                                    state: Dict[str, Any]):
        """
        The exchange's stoploss order filled, so record that exit at the price
        it actually got. No new order is sent -- the position is already flat.
        """
        exit_price = state.get("avg_price") or trade["stoploss"]
        pnl = paper_trading.calculate_pnl(trade, exit_price)

        if not db.mark_exited(trade["id"], exit_price, "STOPLOSS",
                              pnl, trade["sl_order_id"]):
            return

        db.set_sl_order(trade["id"], None)
        self._exit_attempts.pop(trade["id"], None)
        if trade.get("signal_id"):
            self._advance_signal(trade["signal_id"], "CLOSED")
        api_runtime.mark_trade()
        api_runtime.bus.emit("TRADE_CLOSED", {
            "trade_id": trade["id"], "symbol": trade["tradingsymbol"],
            "exit_price": exit_price, "pnl": pnl, "reason": "STOPLOSS",
        })
        emoji = "🟢" if pnl > 0 else "🔴"
        await self.notify(
            f"{emoji} STOPLOSS FILLED AT EXCHANGE #{trade['id']}  "
            f"{trade['tradingsymbol']}\n"
            f"   Exit ₹{exit_price:.2f}  |  P&L: ₹{pnl:+.2f}\n"
            f"   Order: {trade['sl_order_id']}"
        )

    async def _exit_trade(self, trade: Dict[str, Any], ltp: float,
                          token: str, reason: str):
        """
        Close an open position.

        In live mode this MUST place a real closing order before the trade is
        recorded as closed. The previous version only wrote to the database, so
        a live run would open a real position at Angel One and then, on SL or
        target, write a row saying "CLOSED, P&L -3,000" and send a Telegram
        message saying the same -- while the actual position stayed open at the
        broker indefinitely, with the bot no longer watching it.

        If the closing order fails the trade is deliberately LEFT ACTIVE so the
        next tick tries again; it is not marked closed, because the position is
        still live. After MAX_ORDER_ATTEMPTS the bot gives up and asks for
        manual intervention rather than hammering the exchange.
        """
        trade_id = trade["id"]
        qty = trade["quantity"] * trade["lot_size"]
        # Closing a long means selling; closing a short means buying back.
        exit_action = "SELL" if trade["action"] == "BUY" else "BUY"
        exit_order_id = None

        if self.mode == "live":
            attempts = self._exit_attempts.get(trade_id, 0)
            if attempts >= MAX_ORDER_ATTEMPTS:
                return  # already escalated; don't keep firing orders

            # Pull the resting stop FIRST. If it fires after our market exit,
            # the second fill reverses the position instead of closing it.
            outcome = await self._cancel_exchange_stop(trade)
            if outcome == "already_filled":
                try:
                    state = self.live_broker.order_state(trade["sl_order_id"])
                    await self._settle_exchange_stop(trade, state)
                except Exception as e:
                    logger.warning(f"Could not settle filled stop: {e}")
                return
            if outcome == "failed":
                return  # stays ACTIVE; already alerted

            self._exit_attempts[trade_id] = attempts + 1
            try:
                exit_order_id = self.live_broker.place_market_order(
                    tradingsymbol=trade["tradingsymbol"],
                    token=token,
                    exchange=trade["exchange"],
                    action=exit_action,
                    quantity=qty,
                )
                exit_fill = await self._await_fill(exit_order_id, fallback=ltp)
            except Exception as e:
                remaining = MAX_ORDER_ATTEMPTS - self._exit_attempts[trade_id]
                if remaining > 0:
                    await self.notify(
                        f"🚨 EXIT ORDER FAILED #{trade_id} {trade['tradingsymbol']}\n"
                        f"   {reason} at ₹{ltp:.2f} but the order was rejected: {e}\n"
                        f"   POSITION IS STILL OPEN. Retrying ({remaining} left)."
                    )
                else:
                    await self.notify(
                        f"🚨🚨 MANUAL ACTION REQUIRED #{trade_id} "
                        f"{trade['tradingsymbol']}\n"
                        f"   Could not close after {MAX_ORDER_ATTEMPTS} attempts: {e}\n"
                        f"   {qty} qty is STILL OPEN at the broker. "
                        f"Close it yourself in the Angel One app NOW."
                    )
                return  # stays ACTIVE on purpose
        else:
            exit_order_id = self.paper.place_market_order(
                trade["tradingsymbol"], token, trade["exchange"],
                exit_action, qty,
            )
            exit_fill = ltp

        pnl = paper_trading.calculate_pnl(trade, exit_fill)
        if not db.mark_exited(trade_id, exit_fill, reason, pnl, exit_order_id):
            logger.warning(f"Trade #{trade_id} was already closed; skipping notify")
            return

        self._exit_attempts.pop(trade_id, None)
        if trade.get("signal_id"):
            self._advance_signal(trade["signal_id"], "CLOSED")
        api_runtime.mark_trade()
        api_runtime.bus.emit("TRADE_CLOSED", {
            "trade_id": trade_id, "symbol": trade["tradingsymbol"],
            "exit_price": exit_fill, "pnl": pnl, "reason": reason,
        })

        if reason == "TRAILING_SL":
            emoji = "🟢" if pnl > 0 else "🔴"
            headline = f"{emoji} TRAILING STOP HIT"
        elif reason == "STOPLOSS":
            emoji = "🟢" if pnl > 0 else "🔴"
            headline = f"{emoji} STOPLOSS HIT"
        else:
            headline = f"🎯 {reason.replace('_', ' ')} HIT"

        await self.notify(
            f"{headline} #{trade_id}  {trade['tradingsymbol']}\n"
            f"   {exit_action} {qty} @ ₹{exit_fill:.2f}  |  P&L: ₹{pnl:+.2f}"
            + (f"\n   Exit order: {exit_order_id}" if self.mode == "live" else "")
        )
