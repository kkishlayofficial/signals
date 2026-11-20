"""
Angel One SmartAPI wrapper.

Handles:
  - Authenticated login (with TOTP or interactive SMS OTP fallback)
  - Instrument-master lookup (resolves tradingsymbol → token)
  - LTP fetching
  - Order placement (market / limit / stoploss)
  - Session persistence (reused until invalidated)

For MCX options the exchange is "MCX"; for NFO options it's "NFO".
"""
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

import pyotp
import requests
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

import config

logger = logging.getLogger(__name__)

INSTRUMENT_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
INSTRUMENT_CACHE = config.BASE_DIR / "instruments.json"
INSTRUMENT_CACHE_TTL_HOURS = 20  # refresh once a day


class BrokerError(Exception):
    pass


# Angel One order-book `status` values, lowercased.
STATUS_FILLED = "complete"
STATUS_DEAD = ("cancelled", "rejected")           # terminal, never filled
STATUS_PENDING = ("open", "trigger pending", "validation pending",
                  "put order req received", "modified", "open pending")


def round_to_tick(price: float, tick: float) -> float:
    """
    Angel rejects a price that isn't a multiple of the instrument's tick size
    ("AB1018 / invalid price"), so every price we send has to be snapped to it.
    """
    if not tick or tick <= 0:
        return round(price, 2)
    return round(round(price / tick) * tick, 2)


class AngelBroker:
    def __init__(self):
        self.api_key = config.ANGEL_API_KEY
        self.client_id = config.ANGEL_CLIENT_ID
        self.password = config.ANGEL_PASSWORD
        self.totp_secret = config.ANGEL_TOTP_SECRET
        self.smart: Optional[SmartConnect] = None
        self.feed_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self._instruments: Optional[List[Dict[str, Any]]] = None
        # Built lazily by build_instrument_index() -- a slim, search-ready
        # view of the master plus an O(1) (exchange, token) lookup, so the
        # dashboard's instrument search/detail doesn't re-scan or re-hold
        # full raw dicts for all ~170k rows.
        self._index: Optional[List[Dict[str, Any]]] = None
        self._index_by_key: Optional[Dict[tuple, Dict[str, Any]]] = None

    # ------------------------------------------------------------------ login
    def login(self) -> None:
        """Login to Angel One. Uses TOTP if provided, else prompts for SMS OTP."""
        logger.info("Logging in to Angel One...")
        self.smart = SmartConnect(api_key=self.api_key)

        if self.totp_secret:
            totp = pyotp.TOTP(self.totp_secret).now()
        else:
            totp = input("Enter OTP received on your phone: ").strip()

        session = self.smart.generateSession(self.client_id, self.password, totp)
        if not session or not session.get("status"):
            raise BrokerError(f"Login failed: {session}")

        self.refresh_token = session["data"]["refreshToken"]
        self.feed_token = self.smart.getfeedToken()
        logger.info("Angel One login successful.")

    # -------------------------------------------------------- instrument list
    def _load_instruments(self) -> List[Dict[str, Any]]:
        """Load the instrument master (cached locally for the day)."""
        if self._instruments is not None:
            return self._instruments

        if INSTRUMENT_CACHE.exists():
            age_hours = (time.time() - INSTRUMENT_CACHE.stat().st_mtime) / 3600
            if age_hours < INSTRUMENT_CACHE_TTL_HOURS:
                logger.info(f"Loading instruments from cache ({age_hours:.1f}h old)")
                with open(INSTRUMENT_CACHE) as f:
                    self._instruments = json.load(f)
                return self._instruments

        logger.info("Downloading instrument master from Angel One...")
        resp = requests.get(INSTRUMENT_URL, timeout=60)
        resp.raise_for_status()
        self._instruments = resp.json()
        with open(INSTRUMENT_CACHE, "w") as f:
            json.dump(self._instruments, f)
        logger.info(f"Cached {len(self._instruments)} instruments.")
        return self._instruments

    # ---------------------------------------------------- instrument search
    def build_instrument_index(self) -> List[Dict[str, Any]]:
        """
        A slim, display/search-ready view of the instrument master -- just
        the fields the dashboard's instrument search and info panel need,
        built once from the ~170k-row master and reused, rather than
        re-scanning (or re-holding) the full raw dicts on every search.

        Note on `strike`: the master's own units for this field are
        inconsistent across instrument types (find_instrument above has to
        try both the raw value and value*100 to match it). This index
        exposes it exactly as the master reports it -- unconverted -- rather
        than guessing a rescaling that could silently show a wrong number;
        callers needing the real rupee strike for a specific option already
        have it from the signal/trade that produced it.
        """
        if self._index is not None:
            return self._index

        raw = self._load_instruments()
        index: List[Dict[str, Any]] = []
        by_key: Dict[tuple, Dict[str, Any]] = {}
        for inst in raw:
            try:
                strike = float(inst.get("strike") or 0)
            except (TypeError, ValueError):
                strike = 0.0
            try:
                lotsize = int(inst.get("lotsize") or 1)
            except (TypeError, ValueError):
                lotsize = 1
            try:
                tick_size = float(inst.get("tick_size") or 0) / 100.0 or 0.05
            except (TypeError, ValueError):
                tick_size = 0.05

            token = inst.get("token")
            exchange = inst.get("exch_seg")
            entry = {
                "token": token,
                "symbol": inst.get("symbol"),
                "name": inst.get("name"),
                "exchange": exchange,
                "instrument_type": inst.get("instrumenttype"),
                "expiry": inst.get("expiry"),
                "strike": strike,
                "lotsize": lotsize,
                "tick_size": tick_size,
            }
            index.append(entry)
            if token and exchange:
                by_key[(exchange, str(token))] = entry

        self._index = index
        self._index_by_key = by_key
        logger.info(f"Built instrument search index: {len(index)} entries.")
        return self._index

    def search_instruments(self, query: str, exchange: Optional[str] = None,
                           limit: int = 20) -> List[Dict[str, Any]]:
        """
        Case-insensitive search over symbol/name. Ranked exact > starts-with
        > contains, each group in master order, then truncated to `limit`.
        """
        self.build_instrument_index()
        q = (query or "").strip().upper()
        if not q:
            return []

        exact, starts, contains = [], [], []
        for entry in self._index:
            if exchange and entry["exchange"] != exchange:
                continue
            symbol = (entry["symbol"] or "").upper()
            name = (entry["name"] or "").upper()
            if symbol == q or name == q:
                exact.append(entry)
            elif symbol.startswith(q) or name.startswith(q):
                starts.append(entry)
            elif q in symbol or q in name:
                contains.append(entry)
            if len(exact) + len(starts) + len(contains) >= limit * 4:
                # Early cutoff -- once we have comfortably more candidates
                # than `limit` across all three buckets, scanning further
                # into a 170k-row list for a lower-ranked match isn't worth it.
                break

        return (exact + starts + contains)[:limit]

    def get_instrument_by_token(self, exchange: str, token: str) -> Optional[Dict[str, Any]]:
        self.build_instrument_index()
        return self._index_by_key.get((exchange, str(token)))

    # ---------------------------------------------------------- candles / quotes
    def get_candles(self, exchange: str, token: str, interval: str,
                    from_dt: str, to_dt: str) -> List[Dict[str, Any]]:
        """
        Historical OHLCV candles.

        `interval` is Angel's own code (e.g. "FIVE_MINUTE") -- callers map
        the API's own interval strings through api.candles.angel_interval_code
        before calling this. `from_dt`/`to_dt` are "YYYY-MM-DD HH:MM".

        Returns a possibly-empty list -- empty/sparse is a normal response
        for a thinly-traded option strike, not an error, and the caller
        (MarketDataService) is the one that decides whether to fall back to
        tick-derived candles. This only raises when the broker call itself
        failed outright.
        """
        if not self.smart:
            raise BrokerError("Not logged in.")
        params = {
            "exchange": exchange,
            "symboltoken": str(token),
            "interval": interval,
            "fromdate": from_dt,
            "todate": to_dt,
        }
        resp = self.smart.getCandleData(params)
        if not resp or not resp.get("status"):
            raise BrokerError(f"getCandleData failed: {resp}")

        out = []
        for row in resp.get("data") or []:
            # Angel's row shape: [timestamp, open, high, low, close, volume]
            if len(row) < 6:
                continue
            out.append({
                "ts": row[0], "o": row[1], "h": row[2], "l": row[3],
                "c": row[4], "v": row[5],
            })
        return out

    def get_market_data_full(self, exchange: str, tokens: List[str]) -> Dict[str, Any]:
        """
        FULL-mode quote for up to ~50 tokens on one exchange: LTP, OHLC,
        volume, best-5 depth, where the instrument type has them.

        Returns {"fetched": {token: {...}}, "unfetched": [token, ...]} --
        callers must check which bucket a requested token landed in rather
        than assuming every token they asked for came back; Angel reports
        indices/commodities without a usable depth book, for example.
        """
        if not self.smart:
            raise BrokerError("Not logged in.")
        resp = self.smart.getMarketData("FULL", {exchange: [str(t) for t in tokens]})
        if not resp or not resp.get("status"):
            raise BrokerError(f"getMarketData failed: {resp}")

        data = resp.get("data") or {}
        fetched = {}
        for row in data.get("fetched") or []:
            token = str(row.get("symbolToken") or row.get("symboltoken") or "")
            if token:
                fetched[token] = row

        # "unfetched" entries have been seen as both plain token strings and
        # {exchange, symbolToken, message} dicts across SmartAPI versions --
        # handled defensively rather than assuming one shape.
        unfetched = []
        for u in data.get("unfetched") or []:
            if isinstance(u, dict):
                tok = u.get("symbolToken") or u.get("symboltoken")
                if tok:
                    unfetched.append(str(tok))
            elif u:
                unfetched.append(str(u))

        return {"fetched": fetched, "unfetched": unfetched}

    def find_instrument(
        self,
        symbol: str,
        expiry_day: int,
        expiry_month: int,
        expiry_year: int,
        strike: float,
        option_type: str,
    ) -> Dict[str, Any]:
        """
        Resolve a signal into an Angel One instrument.
        Returns a dict with `token`, `symbol`, `exch_seg`, `lotsize`.
        """
        instruments = self._load_instruments()

        months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                  "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
        expiry_str = f"{expiry_day:02d}{months[expiry_month - 1]}{expiry_year}"

        # Strike is stored in paise-like format sometimes; angel uses *100 for
        # certain segments. For MCX/NFO options the strike field is the raw
        # price × 100 in the master. Try both.
        strike_candidates = {str(int(strike * 100)), str(int(strike)), str(strike)}

        matches = []
        for inst in instruments:
            if inst.get("instrumenttype") not in ("OPTFUT", "OPTIDX", "OPTCUR", "OPTSTK"):
                continue
            if inst.get("name", "").upper() != symbol.upper():
                continue
            # Angel stores expiry as e.g. "17NOV2026"
            if expiry_str not in (inst.get("expiry", "") or "").upper():
                continue
            if (inst.get("strike") or "").split(".")[0] not in strike_candidates:
                continue
            tsym = inst.get("symbol", "").upper()
            if not tsym.endswith(option_type):
                continue
            matches.append(inst)

        if not matches:
            raise BrokerError(
                f"No instrument found for {symbol} {expiry_str} {int(strike)} {option_type}"
            )
        if len(matches) > 1:
            logger.warning(f"Multiple matches for {symbol} {expiry_str} {strike} {option_type}: "
                           f"{[m.get('symbol') for m in matches]}, using first")

        inst = matches[0]
        # tick_size in the master is in paise (e.g. "10.000000" -> ₹0.10).
        try:
            tick = float(inst.get("tick_size") or 0) / 100.0
        except (TypeError, ValueError):
            tick = 0.0

        return {
            "token": inst["token"],
            "symbol": inst["symbol"],
            "exch_seg": inst["exch_seg"],
            "lotsize": int(inst.get("lotsize") or 1),
            "ticksize": tick or 0.05,
        }

    # ---------------------------------------------------------------- quotes
    def get_ltp(self, exchange: str, tradingsymbol: str, token: str) -> float:
        """Last traded price for an instrument."""
        if not self.smart:
            raise BrokerError("Not logged in. Call login() first.")

        resp = self.smart.ltpData(exchange, tradingsymbol, token)
        if not resp or not resp.get("status"):
            raise BrokerError(f"LTP fetch failed: {resp}")
        return float(resp["data"]["ltp"])

    # ----------------------------------------------------------- order status
    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        One order from the order book, or None if it isn't there yet.

        Needed for two things the bot cannot work out from the price feed
        alone: the price an order actually filled at, and whether a resting
        stoploss order has already been triggered by the exchange.
        """
        if not self.smart:
            raise BrokerError("Not logged in.")

        resp = self.smart.orderBook()
        if not resp or not resp.get("status"):
            raise BrokerError(f"Order book fetch failed: {resp}")

        for o in resp.get("data") or []:
            if str(o.get("orderid")) == str(order_id):
                return o
        return None

    def order_state(self, order_id: str) -> Dict[str, Any]:
        """
        Normalised view of an order: {state, status, avg_price, filled_qty}.

        `state` is one of "filled", "dead", "pending", "unknown" -- "unknown"
        meaning the order isn't in the book yet, which is NOT the same as
        rejected and must never be treated as "safe to re-send".
        """
        o = self.get_order(order_id)
        if o is None:
            return {"state": "unknown", "status": None, "avg_price": None,
                    "filled_qty": 0}

        status = str(o.get("status") or o.get("orderstatus") or "").lower().strip()
        try:
            avg = float(o.get("averageprice") or 0) or None
        except (TypeError, ValueError):
            avg = None
        try:
            filled = int(float(o.get("filledshares") or 0))
        except (TypeError, ValueError):
            filled = 0

        if status == STATUS_FILLED:
            state = "filled"
        elif status in STATUS_DEAD:
            state = "dead"
        elif status in STATUS_PENDING:
            state = "pending"
        else:
            state = "pending"  # unrecognised but live; don't assume it's gone

        return {"state": state, "status": status, "avg_price": avg,
                "filled_qty": filled}

    # ---------------------------------------------------------------- orders
    def place_market_order(
        self,
        tradingsymbol: str,
        token: str,
        exchange: str,
        action: str,                 # "BUY" or "SELL"
        quantity: int,
        product_type: str = "INTRADAY",
    ) -> str:
        """Place a MARKET order. Returns the broker's order ID."""
        if not self.smart:
            raise BrokerError("Not logged in.")

        params = {
            "variety": "NORMAL",
            "tradingsymbol": tradingsymbol,
            "symboltoken": token,
            "transactiontype": action,
            "exchange": exchange,
            "ordertype": "MARKET",
            "producttype": product_type,
            "duration": "DAY",
            "price": "0",
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity),
        }
        logger.info(f"Placing MARKET order: {action} {quantity} {tradingsymbol}")
        order_id = self.smart.placeOrder(params)
        logger.info(f"Order placed: {order_id}")
        return order_id

    def place_limit_order(
        self,
        tradingsymbol: str,
        token: str,
        exchange: str,
        action: str,
        quantity: int,
        limit_price: float,
        product_type: str = "INTRADAY",
        ticksize: float = 0.05,
    ) -> str:
        """Place a LIMIT order. Returns the broker's order ID."""
        if not self.smart:
            raise BrokerError("Not logged in.")

        limit_price = round_to_tick(limit_price, ticksize)

        params = {
            "variety": "NORMAL",
            "tradingsymbol": tradingsymbol,
            "symboltoken": token,
            "transactiontype": action,
            "exchange": exchange,
            "ordertype": "LIMIT",
            "producttype": product_type,
            "duration": "DAY",
            "price": str(limit_price),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity),
        }
        logger.info(f"Placing LIMIT order: {action} {quantity} {tradingsymbol} @ {limit_price}")
        order_id = self.smart.placeOrder(params)
        logger.info(f"Limit order placed: {order_id}")
        return order_id

    def place_sl_order(
        self,
        tradingsymbol: str,
        token: str,
        exchange: str,
        action: str,
        quantity: int,
        trigger_price: float,
        limit_price: float,
        product_type: str = "INTRADAY",
        ticksize: float = 0.05,
    ) -> str:
        """Place a STOPLOSS-LIMIT order."""
        if not self.smart:
            raise BrokerError("Not logged in.")

        trigger_price = round_to_tick(trigger_price, ticksize)
        limit_price = round_to_tick(limit_price, ticksize)

        params = {
            "variety": "STOPLOSS",
            "tradingsymbol": tradingsymbol,
            "symboltoken": token,
            "transactiontype": action,
            "exchange": exchange,
            "ordertype": "STOPLOSS_LIMIT",
            "producttype": product_type,
            "duration": "DAY",
            "price": str(limit_price),
            "triggerprice": str(trigger_price),
            "quantity": str(quantity),
        }
        logger.info(f"Placing SL order: {action} {quantity} {tradingsymbol} "
                    f"@ trigger {trigger_price} / limit {limit_price}")
        return self.smart.placeOrder(params)

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        if not self.smart:
            raise BrokerError("Not logged in.")
        resp = self.smart.cancelOrder(order_id, variety)
        return bool(resp and resp.get("status"))

    # ------------------------------------------------------------ websocket
    def create_ticker(self, on_tick: Callable[[str, float], None]) -> "AngelTicker":
        """
        Create a WebSocket ticker that pushes real-time LTP updates.

        `on_tick(token, ltp)` is called from a background thread on every
        price update.  The caller must bridge it into the async loop.
        """
        if not self.smart or not self.feed_token or not self.client_id:
            raise BrokerError("Not logged in — no feed token for WebSocket.")
        return AngelTicker(
            auth_token=self.smart.access_token,
            api_key=self.api_key,
            client_code=self.client_id,
            feed_token=self.feed_token,
            on_tick=on_tick,
        )

    def logout(self):
        if self.smart:
            try:
                self.smart.terminateSession(self.client_id)
            except Exception:
                pass
            logger.info("Logged out of Angel One.")


# ------------------------------------------------------------------ ticker

# SmartWebSocketV2 exchange type codes (integer, not string).
_EXCH_MAP_V2: Dict[str, int] = {
    "NSE": SmartWebSocketV2.NSE_CM,   # 1
    "NFO": SmartWebSocketV2.NSE_FO,   # 2
    "BSE": SmartWebSocketV2.BSE_CM,   # 3
    "BFO": SmartWebSocketV2.BSE_FO,   # 4
    "MCX": SmartWebSocketV2.MCX_FO,   # 5
    "CDS": SmartWebSocketV2.CDE_FO,   # 13
}


class AngelTicker:
    """
    Real-time price feed via Angel One SmartStream WebSocket (V2).

    Runs in a daemon thread so it doesn't block the asyncio loop.
    Call `subscribe(exchange, token)` to start receiving ticks for an
    instrument and `on_tick(token, ltp)` fires on every price update.
    """

    def __init__(self, auth_token: str, api_key: str, client_code: str,
                 feed_token: str, on_tick: Callable[[str, float], None]):
        self._auth_token = auth_token
        self._api_key = api_key
        self._client_code = client_code
        self._feed_token = feed_token
        self._on_tick = on_tick
        self._ws: Optional[SmartWebSocketV2] = None
        self._subscribed: Dict[int, set] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._ws = SmartWebSocketV2(
            self._auth_token, self._api_key,
            self._client_code, self._feed_token,
            max_retry_attempt=3, retry_strategy=0, retry_delay=5,
        )
        self._ws.on_data = self._handle_data
        self._ws.on_open = self._handle_open
        self._ws.on_error = self._handle_error
        self._ws.on_close = self._handle_close

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("WebSocket V2 ticker started.")

    def _run(self):
        try:
            self._ws.connect()
        except Exception as e:
            logger.error(f"WebSocket V2 connection failed: {e}")
            self._running = False

    def subscribe(self, exchange: str, token: str):
        exch_type = _EXCH_MAP_V2.get(exchange.upper())
        if exch_type is None:
            logger.warning(f"Unknown exchange {exchange} for WebSocket; skipping")
            return
        if exch_type not in self._subscribed:
            self._subscribed[exch_type] = set()
        if token in self._subscribed[exch_type]:
            return
        self._subscribed[exch_type].add(token)
        if self._running and self._ws and self._ws.wsapp:
            try:
                token_list = [{"exchangeType": exch_type, "tokens": [token]}]
                self._ws.subscribe("ticker", SmartWebSocketV2.LTP_MODE, token_list)
                logger.debug(f"WS subscribed: {exchange}:{token}")
            except Exception as e:
                logger.warning(f"WS subscribe failed for {exchange}:{token}: {e}")

    def unsubscribe(self, exchange: str, token: str):
        """
        Stop receiving ticks for a token.

        Callers (MarketDataService) must only call this for a token no
        longer wanted by ANY viewer AND not held by any open trade -- this
        method itself has no idea which callers still want this token, it
        just does what it's told.
        """
        exch_type = _EXCH_MAP_V2.get(exchange.upper())
        if exch_type is None or exch_type not in self._subscribed:
            return
        if token not in self._subscribed[exch_type]:
            return
        self._subscribed[exch_type].discard(token)
        if self._running and self._ws and self._ws.wsapp:
            try:
                token_list = [{"exchangeType": exch_type, "tokens": [token]}]
                self._ws.unsubscribe("ticker", SmartWebSocketV2.LTP_MODE, token_list)
                logger.debug(f"WS unsubscribed: {exchange}:{token}")
            except Exception as e:
                logger.warning(f"WS unsubscribe failed for {exchange}:{token}: {e}")

    def _handle_open(self, wsapp):
        logger.info("WebSocket V2 connected — resubscribing to all instruments.")
        self._running = True
        for exch_type, tokens in self._subscribed.items():
            if tokens:
                try:
                    token_list = [{"exchangeType": exch_type, "tokens": list(tokens)}]
                    self._ws.subscribe("ticker", SmartWebSocketV2.LTP_MODE, token_list)
                except Exception as e:
                    logger.warning(f"WS resubscribe failed for exchange type {exch_type}: {e}")

    def _handle_data(self, wsapp, data):
        token = str(data.get("token") or "").strip()
        ltp_raw = data.get("last_traded_price")
        if token and ltp_raw is not None:
            try:
                self._on_tick(token, float(ltp_raw) / 100.0)
            except Exception as e:
                logger.debug(f"on_tick callback error: {e}")

    def _handle_error(self, *args):
        logger.warning(f"WebSocket V2 error: {args}")

    def _handle_close(self, wsapp):
        logger.info("WebSocket V2 closed.")
        self._running = False

    def stop(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close_connection()
            except Exception:
                pass
