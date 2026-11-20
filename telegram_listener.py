"""
Telegram listener using Telethon.

Signs in as the user (via api_id + api_hash + phone — this is the
User API, not the Bot API, which means it can read any channel the
user is subscribed to, including private paid channels).

On each new message in a monitored channel it:
  1. Checks if it looks like a signal
  2. Parses it
  3. Hands it to the TradeManager
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable, Optional

from telethon import TelegramClient, events

import config
import database as db
from signal_parser import (parse_signal, parse_targets_only, looks_like_signal,
                           SignalParseError)

from api.runtime import runtime as api_runtime

logger = logging.getLogger(__name__)


def _is_bare_number(text: str) -> bool:
    """True when the message is just a price (optionally with emoji/punctuation)."""
    alpha_num = re.sub(r'[^a-zA-Z0-9.]', '', text)
    return bool(re.fullmatch(r'\d+(?:\.\d+)?', alpha_num))


class TelegramListener:
    def __init__(self, on_signal: Callable[[object], Awaitable[None]],
                 on_targets: Optional[Callable[..., Awaitable[None]]] = None):
        """
        on_signal:  async callback invoked with each ParsedSignal.
        on_targets: async callback invoked with (targets, quoted_text) when a
                    message carries only a target line, which is how these
                    channels post the target for a signal sent moments earlier.
        """
        self.on_signal = on_signal
        self.on_targets = on_targets
        self.client = TelegramClient(
            str(config.SESSION_PATH).replace(".session", ""),
            config.TELEGRAM_API_ID,
            config.TELEGRAM_API_HASH,
        )
        self._entities = []
        self._handler = None
        self._last_activity = datetime.now(timezone.utc)
        self._stopping = False

    async def _handle_message(self, text: str, quoted: Optional[str],
                              channel_name: str = "", msg_date: Optional[datetime] = None,
                              quoted_date: Optional[datetime] = None):
        """Process one message through the signal/target pipeline."""
        now = datetime.now(timezone.utc)
        self._last_activity = now
        preview = text[:80].replace('\n', ' ').strip()

        if msg_date is not None:
            delay = (now - msg_date).total_seconds()
            logger.info(f"Processing: {preview!r}  (posted {delay:.1f}s ago)")
            if delay > 3:
                logger.warning(
                    f"Channel message took {delay:.1f}s to reach the handler "
                    f"(posted {msg_date.isoformat()}, handled {now.isoformat()})."
                )
        else:
            logger.info(f"Processing: {preview!r}")

        if _is_bare_number(text):
            logger.info(f"  -> position update (bare number), skipping")
            self._log_message(channel_name, text, "skipped", msg_date)
            return

        targets = parse_targets_only(text)
        if targets and self.on_targets:
            logger.info(f"  -> target follow-up: {targets}")
            self._log_message(channel_name, text, "target", msg_date)
            try:
                await self.on_targets(targets, quoted_text=quoted)
            except Exception as e:
                logger.exception(f"on_targets handler failed: {e}")
            return

        # A message that at least looks like a signal attempt gets a row in
        # the signals lifecycle table the moment it's recognised as one --
        # before we even know whether it will parse. Pure chatter (nothing
        # below matches looks_like_signal) never gets a row here; that's
        # what channel_messages' "ignored" parse_result already covers.
        # A reply only inherits the quoted message's signal when that
        # message is still fresh. Otherwise an unrelated reply sent hours
        # later (even a one-word "Gh") would stitch onto a stale -- possibly
        # already-rejected -- signal and get parsed as a brand-new one.
        quoted_is_fresh = (
            quoted_date is not None and msg_date is not None and
            (msg_date - quoted_date) <= timedelta(
                minutes=config.TELEGRAM_QUOTE_REPLY_MAX_AGE_MINUTES)
        ) if quoted else False
        if quoted and not quoted_is_fresh:
            logger.info(
                f"  -> reply quotes a stale message "
                f"({quoted_date}), ignoring the quote")
            quoted = None

        candidates_tried = False
        parse_errors: list = []
        best = None
        signal_id = None
        for candidate in (text, f"{quoted}\n{text}" if quoted else None):
            if not candidate or not looks_like_signal(candidate):
                continue
            if not candidates_tried:
                signal_id = self._record_signal_received(channel_name, text, msg_date)
            candidates_tried = True
            try:
                sig = parse_signal(candidate)
            except SignalParseError as e:
                logger.info(f"  -> not a valid signal ({e})")
                parse_errors.append(str(e))
                continue
            if best is None or (sig.targets_explicit and not best.targets_explicit):
                best = sig

        if best is None:
            logger.info(f"  -> ignored (not a signal)")
            self._log_message(channel_name, text, "ignored", msg_date)
            if signal_id:
                db.update_signal(
                    signal_id, status="INVALID",
                    reject_reason="; ".join(parse_errors)[:500] or "no instrument/entry/stoploss found",
                )
                api_runtime.bus.emit("SIGNAL_REJECTED", {
                    "signal_id": signal_id,
                    "reason": "; ".join(parse_errors)[:500] or "unparseable",
                })
            return

        logger.info(f"  -> SIGNAL: {best.tradingsymbol}")
        msg_id = self._log_message(channel_name, text, "signal", msg_date)
        if signal_id:
            db.update_signal(signal_id, status="PARSED", parsed_json=json.dumps({
                "symbol": best.symbol, "tradingsymbol": best.tradingsymbol,
                "action": best.action, "entry_condition": best.entry_condition,
                "entry_price": best.entry_price, "stoploss": best.stoploss,
                "targets": best.targets, "targets_explicit": best.targets_explicit,
                "option_type": best.option_type, "strike": best.strike,
                "expiry_day": best.expiry_day, "expiry_month": best.expiry_month,
                "expiry_year": best.expiry_year,
            }))
            api_runtime.bus.emit("SIGNAL_PARSED", {
                "signal_id": signal_id, "tradingsymbol": best.tradingsymbol,
                "action": best.action, "entry_price": best.entry_price,
            })

        trade_id = None
        try:
            trade_id = await self.on_signal(best, signal_id=signal_id)
        except Exception as e:
            logger.exception(f"on_signal handler failed: {e}")
            if signal_id:
                db.update_signal(signal_id, status="REJECTED", reject_reason=f"handler error: {e}")
            return

        if msg_id and trade_id:
            try:
                db.update_message_trade(msg_id, trade_id)
            except Exception as e:
                logger.warning(f"Failed to link message {msg_id} to trade {trade_id}: {e}")

    def _record_signal_received(self, channel_name: str, text: str,
                                msg_date: Optional[datetime]) -> Optional[int]:
        try:
            signal_id = db.insert_signal(
                raw_text=text, status="RECEIVED",
                channel_name=channel_name, received_at=msg_date,
            )
        except Exception as e:
            logger.warning(f"Failed to record signal attempt: {e}")
            return None
        api_runtime.mark_signal()
        api_runtime.bus.emit("SIGNAL_RECEIVED", {
            "signal_id": signal_id, "channel": channel_name,
            "preview": text[:200],
        })
        return signal_id

    @staticmethod
    def _log_message(channel_name: str, text: str, result: str,
                     msg_date: Optional[datetime] = None) -> Optional[int]:
        try:
            return db.insert_message(channel_name, text, result, received_at=msg_date)
        except Exception as e:
            logger.warning(f"Failed to log channel message: {e}")
            return None

    async def connect(self):
        """
        Sign in and register the message handler, but don't block yet.

        Returns the number of channels successfully resolved.
        """
        logger.info("Connecting to Telegram…")
        await self.client.start(phone=config.TELEGRAM_PHONE)

        me = await self.client.get_me()
        logger.info(f"Logged in as @{me.username or me.first_name} (id={me.id})")

        self._entities = []
        for chan in config.TELEGRAM_SIGNAL_CHANNELS:
            try:
                ent = await self.client.get_entity(chan)
                self._entities.append(ent)
                logger.info(f"Monitoring: {getattr(ent, 'title', chan)}")
            except Exception as e:
                logger.warning(f"Could not resolve channel '{chan}': {e}")

        if not self._entities:
            logger.error("No valid channels to monitor. Check TELEGRAM_SIGNAL_CHANNELS in .env.")
            return 0

        if self._handler is not None:
            self.client.remove_event_handler(self._handler)

        @self.client.on(events.NewMessage(chats=self._entities))
        async def _handler(event):
            text = event.message.message or ""
            chan = getattr(event.chat, 'title', str(event.chat_id)) if event.chat else ""
            quoted = None
            quoted_date = None
            if event.message.reply_to is not None:
                try:
                    parent = await event.message.get_reply_message()
                    if parent is not None:
                        quoted = parent.message or None
                        quoted_date = parent.date
                except Exception as e:
                    logger.warning(f"Could not fetch the quoted message: {e}")
            await self._handle_message(text, quoted, chan, msg_date=event.message.date,
                                       quoted_date=quoted_date)

        self._handler = _handler
        self._last_activity = datetime.now(timezone.utc)
        return len(self._entities)

    async def catch_up(self, limit: int = 30, max_age_minutes: float = 120):
        """
        Scan recent channel messages so signals that arrived while the bot
        was offline are not missed.  Processes oldest-first so signal →
        target order is preserved.  The duplicate guard in TradeManager
        prevents double-opening trades that are already in the DB.
        """
        if not self._entities:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        logger.info(f"Catching up: last {limit} msgs per channel "
                     f"(max age {max_age_minutes:.0f} min)…")

        for entity in self._entities:
            title = getattr(entity, 'title', '?')
            messages = []
            async for msg in self.client.iter_messages(entity, limit=limit):
                messages.append(msg)

            processed = 0
            for msg in reversed(messages):
                if msg.date and msg.date < cutoff:
                    continue
                text = msg.message or ""
                if not text.strip():
                    continue
                quoted = None
                quoted_date = None
                if msg.reply_to is not None:
                    try:
                        parent = await msg.get_reply_message()
                        if parent is not None:
                            quoted = parent.message or None
                            quoted_date = parent.date
                    except Exception:
                        pass
                try:
                    await self._handle_message(text, quoted, title, msg_date=msg.date,
                                               quoted_date=quoted_date)
                    processed += 1
                except Exception as e:
                    logger.warning(f"Catch-up error: {e}")
            logger.info(f"Catch-up done for {title}: processed {processed} of {len(messages)}")

    async def run(self):
        """
        Block until stop() is called. Call connect() first.

        Loops around run_until_disconnected() rather than awaiting it once,
        because the watchdog's reconnect also goes through a disconnect --
        without the loop, that disconnect would make this return and look
        (to main.py) like the listener task finished, which tears down the
        whole bot instead of just the Telegram client.
        """
        logger.info("Telegram listener is live. Waiting for messages…")
        while not self._stopping:
            await self.client.run_until_disconnected()
            if self._stopping:
                break
            logger.warning("Telegram client disconnected -- waiting for reconnect…")
            await asyncio.sleep(1)

    async def watchdog(self, idle_minutes: Optional[float] = None,
                        catchup_seconds: Optional[float] = None,
                        check_interval: float = 15):
        """
        Telethon can end up with a connection that looks alive (no
        disconnect logged, socket still open) but whose update stream has
        gone silently stale -- nothing fires, not even for the channel's
        constant non-signal chatter, until something resyncs it. Waiting
        for the full idle_minutes before noticing left live entry signals
        sitting undelivered for up to that long.

        Two tiers:
          - every catchup_seconds of silence, nudge the client with the
            built-in catch_up() -- a cheap local resync (no disconnect, no
            re-login, no re-registering the handler) that flushes most
            staleness almost immediately.
          - if the channel is *still* silent after idle_minutes, assume the
            nudge alone didn't fix it and force a full disconnect/connect()
            to re-resolve entities and re-register the handler.
        """
        idle_minutes = config.TELEGRAM_WATCHDOG_IDLE_MINUTES if idle_minutes is None else idle_minutes
        catchup_seconds = (config.TELEGRAM_CATCHUP_SECONDS if catchup_seconds is None
                           else catchup_seconds)
        if not idle_minutes or idle_minutes <= 0:
            return
        idle_limit = timedelta(minutes=idle_minutes)
        catchup_limit = (timedelta(seconds=catchup_seconds)
                         if catchup_seconds and catchup_seconds > 0 else None)
        last_catchup = datetime.now(timezone.utc)

        while True:
            await asyncio.sleep(check_interval)
            now = datetime.now(timezone.utc)
            idle_for = now - self._last_activity

            if idle_for > idle_limit:
                logger.warning(
                    f"No channel activity for {idle_for.total_seconds() / 60:.1f} min "
                    f"(limit {idle_minutes:.0f}) -- forcing a Telegram reconnect."
                )
                try:
                    await self.client.disconnect()
                except Exception as e:
                    logger.warning(f"Watchdog disconnect failed: {e}")

                try:
                    n = await self.connect()
                except Exception as e:
                    logger.error(f"Watchdog reconnect failed: {e}")
                    continue

                last_catchup = datetime.now(timezone.utc)
                if n:
                    logger.info(f"Watchdog reconnect succeeded, monitoring {n} channel(s) again.")
                else:
                    logger.error("Watchdog reconnect could not resolve any channels.")
                continue

            if catchup_limit and idle_for > catchup_limit and now - last_catchup > catchup_limit:
                last_catchup = now
                try:
                    await self.client.catch_up()
                    logger.debug(
                        f"Watchdog nudge: catch_up() after {idle_for.total_seconds():.0f}s "
                        f"of silence."
                    )
                except Exception as e:
                    logger.warning(f"Watchdog catch_up() failed: {e}")

    async def start(self):
        """Connect and then block (kept for standalone use)."""
        if await self.connect():
            await self.run()

    async def stop(self):
        self._stopping = True
        await self.client.disconnect()
