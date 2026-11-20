"""
MarketDataService -- instrument search, quotes/depth, historical + live
candles, and viewer subscription management.

Owns none of the bot's core state: it reads the broker and the trade
manager's live ticker through the shared Runtime, and it never creates a
second Angel session or a second WebSocket connection. Every broker call
here is rate-limited and runs off the event loop via asyncio.to_thread --
none of this may ever compete with, or block, the trading loop's own
get_ltp/order calls.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import database as db
from api.candles import INTERVALS, aggregate_ticks_to_candles, angel_interval_code, bucket_start
from api.ratelimit import TokenBucket

logger = logging.getLogger(__name__)

# A token is "stale" if no tick has arrived for this long. 15s matches the
# plan's own threshold; it's deliberately short -- this is a UI badge, not a
# trading decision.
STALE_AFTER_SECONDS = 15.0

# Viewer-driven live-candle emission is coalesced to this cadence per
# (token, interval), matching PRICE_UPDATE's own ~4/s cap elsewhere.
MIN_EMIT_INTERVAL = 0.25

MAX_VIEWER_TOKENS = 30

# A broker candle response below this fraction of the naively-expected count
# for the requested range is treated the same as "empty" -- sparse, not
# trustworthy as the sole source -- and the tick fallback takes over
# entirely rather than being merged in candle-by-candle.
SPARSE_FRACTION = 0.2
SPARSE_MIN_EXPECTED = 5  # below this, a short range is never called "sparse"


class MarketDataService:
    def __init__(self, runtime):
        self.runtime = runtime
        self._candle_limiter = TokenBucket(rate_per_sec=3, capacity=5)
        self._quote_limiter = TokenBucket(rate_per_sec=5, capacity=10)

        self._quote_cache: Dict[tuple, tuple] = {}  # (exchange, token) -> (fetched_at, quote)
        self._quote_cache_ttl = 2.0

        # token -> {"exchange", "intervals": {interval: refcount}, "last_touch"}
        # Refcounted, not a plain set: two viewers (e.g. two browser tabs)
        # can both watch the same (token, interval), and one disconnecting
        # must not kill the feed for the other.
        self._viewer_subs: Dict[str, Dict[str, Any]] = {}
        # (token, interval) -> {"bucket": datetime, "o","h","l","c"}
        self._forming: Dict[tuple, Dict[str, Any]] = {}
        self._last_candle_emit: Dict[tuple, float] = {}
        self._last_tick_at: Dict[str, float] = {}

    # ---------------------------------------------------- instrument search

    async def search_instruments(self, query: str, exchange: Optional[str] = None,
                                  limit: int = 20) -> List[Dict[str, Any]]:
        broker = self.runtime.broker
        if broker is None:
            return []
        return await asyncio.to_thread(broker.search_instruments, query, exchange, limit)

    async def get_instrument(self, exchange: str, token: str) -> Optional[Dict[str, Any]]:
        broker = self.runtime.broker
        if broker is None:
            return None
        return await asyncio.to_thread(broker.get_instrument_by_token, exchange, str(token))

    # ---------------------------------------------------------- quote/depth

    async def get_quote(self, exchange: str, token: str) -> Dict[str, Any]:
        token = str(token)
        key = (exchange, token)
        now = time.monotonic()
        cached = self._quote_cache.get(key)
        if cached and now - cached[0] < self._quote_cache_ttl:
            return cached[1]

        broker = self.runtime.broker
        if broker is None:
            return {"available": False, "reason": "broker not connected", "source": "broker"}

        await self._quote_limiter.acquire()
        try:
            result = await asyncio.to_thread(broker.get_market_data_full, exchange, [token])
        except Exception as e:
            logger.warning(f"get_market_data_full failed for {exchange}:{token}: {e}")
            return {"available": False, "reason": str(e), "source": "broker"}

        row = result["fetched"].get(token)
        if row is None:
            return {"available": False, "reason": "not returned by broker", "source": "broker"}

        quote = self._normalize_quote(row)
        quote["available"] = True
        quote["source"] = "broker"
        quote["stale"] = self.is_stale(token)
        self._quote_cache[key] = (now, quote)
        return quote

    @staticmethod
    def _normalize_quote(row: Dict[str, Any]) -> Dict[str, Any]:
        depth = row.get("depth") or {}
        bid = depth.get("buy") or []
        ask = depth.get("sell") or []
        return {
            "ltp": row.get("ltp"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "prev_close": row.get("close"),  # Angel's FULL "close" is the previous session's
            "volume": row.get("tradeVolume"),
            "vwap": row.get("avgPrice"),
            "net_change": row.get("netChange"),
            "pct_change": row.get("percentChange"),
            "depth": {"bid": bid, "ask": ask, "available": bool(bid or ask)},
            "exch_feed_time": row.get("exchFeedTime"),
        }

    async def get_depth(self, exchange: str, token: str) -> Dict[str, Any]:
        quote = await self.get_quote(exchange, token)
        if not quote.get("available"):
            return {"available": False, "reason": quote.get("reason"), "source": quote.get("source")}
        return {
            "available": quote["depth"]["available"],
            "bid": quote["depth"]["bid"],
            "ask": quote["depth"]["ask"],
            "stale": quote.get("stale"),
            "source": "broker",
        }

    # -------------------------------------------------------------- history

    async def get_history(self, exchange: str, token: str, interval: str,
                          from_dt: datetime, to_dt: datetime) -> Dict[str, Any]:
        token = str(token)
        if interval not in INTERVALS:
            raise ValueError(f"Unknown interval: {interval}")

        # tick_history.ts (database.py) is stored as naive LOCAL time
        # (datetime.now().isoformat(), no tzinfo) -- that convention is used
        # consistently everywhere else in this codebase, so the range given
        # to the tick-fallback query is converted to match it here, rather
        # than comparing a UTC-aware bound against naive-local strings
        # (which silently drops rows by the local UTC offset, IST +5:30 on
        # this deployment).
        from_iso_local = from_dt.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
        to_iso_local = to_dt.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
        expected = max(1, int((to_dt - from_dt).total_seconds() // INTERVALS[interval].seconds))

        broker_candles: List[Dict[str, Any]] = []
        broker_error: Optional[str] = None
        broker = self.runtime.broker
        if broker is not None:
            await self._candle_limiter.acquire()
            try:
                broker_candles = await asyncio.to_thread(
                    broker.get_candles, exchange, token, angel_interval_code(interval),
                    from_dt.strftime("%Y-%m-%d %H:%M"), to_dt.strftime("%Y-%m-%d %H:%M"),
                )
            except Exception as e:
                broker_error = str(e)
                logger.warning(f"get_candles failed for {exchange}:{token} {interval}: {e}")

        is_sparse = (
            expected >= SPARSE_MIN_EXPECTED
            and len(broker_candles) < expected * SPARSE_FRACTION
        )

        if broker_candles and not is_sparse:
            try:
                await asyncio.to_thread(db.upsert_candles, exchange, token, interval, broker_candles)
            except Exception as e:
                logger.debug(f"candle cache write failed: {e}")
            candles = broker_candles
            source = "broker"
        else:
            # Empty, sparse, or the broker call itself failed -- fall back
            # wholesale to ticks rather than mixing two sources in one
            # response (see the Phase 1 plan's "always honest about which
            # source is on screen").
            ticks = await asyncio.to_thread(
                db.get_tick_history_for_token, exchange, token, from_iso_local, to_iso_local,
            )
            candles = aggregate_ticks_to_candles(ticks, interval)
            source = "ticks" if candles else None

        if not candles:
            return {
                "candles": [], "source": None, "available": False, "partial_last": False,
                "reason": broker_error or "no broker data and no recorded ticks for this instrument",
            }

        last_bucket_end = _parse_candle_ts(candles[-1]["ts"]) + _as_timedelta(INTERVALS[interval].seconds)
        partial_last = last_bucket_end > datetime.now(timezone.utc)

        return {"candles": candles, "source": source, "available": True, "partial_last": partial_last}

    # ------------------------------------------------------- viewer subscriptions

    def _ticker(self):
        tm = self.runtime.trade_manager
        return getattr(tm, "_ticker", None) if tm else None

    def _is_trade_held(self, token: str) -> bool:
        tm = self.runtime.trade_manager
        if tm is None:
            return False
        return token in getattr(tm, "_ws_registry", {})

    def subscribe_viewer(self, exchange: str, token: str, interval: str) -> None:
        """
        Each call increments a refcount for (token, interval) -- callers
        (one per WS connection that asked for this) must each later call
        unsubscribe_viewer exactly once for every subscribe_viewer call they
        made, so one connection's cleanup never drops another's feed.
        """
        if interval not in INTERVALS:
            raise ValueError(f"Unknown interval: {interval}")
        token = str(token)
        sub = self._viewer_subs.get(token)
        if sub is None:
            if len(self._viewer_subs) >= MAX_VIEWER_TOKENS:
                self._evict_one_viewer_token()
            sub = {"exchange": exchange, "intervals": {}, "last_touch": time.time()}
            self._viewer_subs[token] = sub
            ticker = self._ticker()
            if ticker:
                ticker.subscribe(exchange, token)
        sub["intervals"][interval] = sub["intervals"].get(interval, 0) + 1
        sub["last_touch"] = time.time()

    def unsubscribe_viewer(self, token: str, interval: Optional[str] = None) -> None:
        """
        Decrements the refcount for (token, interval) from a matching
        subscribe_viewer call. `interval=None` is for forced eviction only
        (_evict_one_viewer_token) -- it tears down every interval on this
        token regardless of refcount, which is only safe because eviction
        picks the least-recently-touched token as a last resort under the
        viewer cap, not a per-connection cleanup path.
        """
        token = str(token)
        sub = self._viewer_subs.get(token)
        if not sub:
            return

        if interval is not None:
            cnt = sub["intervals"].get(interval, 0) - 1
            if cnt > 0:
                sub["intervals"][interval] = cnt
            else:
                sub["intervals"].pop(interval, None)
        else:
            sub["intervals"].clear()

        if not sub["intervals"]:
            # Nothing left watching this token at the viewer layer. Only the
            # ticker subscription that the viewer layer itself added is ever
            # torn down here -- a token also held by an open trade keeps its
            # trade-driven subscription regardless (that one isn't ours to
            # touch; TradeManager owns it completely).
            if not self._is_trade_held(token):
                ticker = self._ticker()
                if ticker:
                    ticker.unsubscribe(sub["exchange"], token)
            self._viewer_subs.pop(token, None)
            self._forming = {k: v for k, v in self._forming.items() if k[0] != token}

    def _evict_one_viewer_token(self) -> None:
        if not self._viewer_subs:
            return
        oldest = min(self._viewer_subs, key=lambda t: self._viewer_subs[t]["last_touch"])
        self.unsubscribe_viewer(oldest)

    # ------------------------------------------------------------ live ticks

    def on_tick(self, token: str, ltp: float) -> None:
        """
        Called synchronously for every tick the shared ticker delivers --
        trade-held tokens included, so an open position's own chart also
        gets live candle updates, not just explicitly-viewed instruments.
        """
        token = str(token)
        now = time.time()
        self._last_tick_at[token] = now

        sub = self._viewer_subs.get(token)
        if not sub:
            return
        for interval in list(sub["intervals"]):
            self._update_forming_candle(token, sub["exchange"], interval, ltp, now)

    def _update_forming_candle(self, token: str, exchange: str, interval: str,
                               ltp: float, now: float) -> None:
        bucket = bucket_start(datetime.fromtimestamp(now, tz=timezone.utc), interval)
        key = (token, interval)
        state = self._forming.get(key)
        closed = None

        if state is None or state["bucket"] != bucket:
            if state is not None:
                closed = dict(state)
            state = {"bucket": bucket, "o": ltp, "h": ltp, "l": ltp, "c": ltp}
            self._forming[key] = state
        else:
            state["h"] = max(state["h"], ltp)
            state["l"] = min(state["l"], ltp)
            state["c"] = ltp

        if closed is not None:
            self._emit_candle(token, exchange, interval, closed, closed_flag=True)
            try:
                db.upsert_candles(exchange, token, interval, [{
                    "ts": closed["bucket"].isoformat(timespec="seconds"),
                    "o": closed["o"], "h": closed["h"], "l": closed["l"], "c": closed["c"], "v": None,
                }])
            except Exception as e:
                logger.debug(f"candle cache write failed on close: {e}")

        last_emit = self._last_candle_emit.get(key, 0)
        if now - last_emit >= MIN_EMIT_INTERVAL:
            self._emit_candle(token, exchange, interval, state, closed_flag=False)
            self._last_candle_emit[key] = now

    def _emit_candle(self, token: str, exchange: str, interval: str,
                     candle: Dict[str, Any], closed_flag: bool) -> None:
        self.runtime.bus.emit("CANDLE_UPDATE", {
            "exchange": exchange, "token": token, "interval": interval,
            "ts": candle["bucket"].isoformat(timespec="seconds"),
            "o": candle["o"], "h": candle["h"], "l": candle["l"], "c": candle["c"],
            "closed": closed_flag,
        })

    # ---------------------------------------------------------------- staleness

    def is_stale(self, token: str, max_age: float = STALE_AFTER_SECONDS) -> bool:
        last = self._last_tick_at.get(str(token))
        if last is None:
            return True  # never ticked -- cannot claim freshness either way
        return (time.time() - last) > max_age


def _parse_candle_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_timedelta(seconds: int):
    from datetime import timedelta
    return timedelta(seconds=seconds)
