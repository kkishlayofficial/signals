"""
SQLite layer for persisting trades, positions, and P&L history.

Schema:
    trades       — one row per signal taken (paper or live)
    exits        — exits recorded against trades (partial targets, SL, manual)
"""
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    mode TEXT NOT NULL,               -- 'paper' or 'live'
    symbol TEXT NOT NULL,
    tradingsymbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    option_type TEXT NOT NULL,        -- 'CE' or 'PE'
    strike REAL NOT NULL,
    expiry TEXT NOT NULL,             -- 'DD-MMM-YYYY'
    action TEXT NOT NULL,             -- 'BUY' or 'SELL'
    quantity INTEGER NOT NULL,
    lot_size INTEGER NOT NULL,
    entry_condition TEXT NOT NULL,    -- 'ABOVE' or 'BELOW'
    entry_trigger REAL NOT NULL,      -- original trigger price from signal
    entry_price REAL,                 -- actual fill price (NULL until triggered)
    entry_time TEXT,                  -- when the trade entered
    stoploss REAL NOT NULL,
    targets TEXT NOT NULL,            -- JSON array of target prices
    status TEXT NOT NULL,             -- PENDING, ACTIVE, CLOSED, CANCELLED
    exit_price REAL,
    exit_time TEXT,
    exit_reason TEXT,                 -- TARGET_1, TARGET_2, STOPLOSS, MANUAL
    pnl REAL,
    broker_order_id TEXT,             -- entry order ID at the broker
    exit_order_id TEXT,               -- exit order ID at the broker
    sl_order_id TEXT,                 -- resting STOPLOSS order at the exchange
    targets_provisional INTEGER DEFAULT 0,  -- 1 = targets invented, awaiting the real ones
    raw_signal TEXT NOT NULL,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_created ON trades(created_at);

CREATE TABLE IF NOT EXISTS tick_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    ltp REAL NOT NULL,
    ts TEXT NOT NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE INDEX IF NOT EXISTS idx_tick_trade ON tick_history(trade_id, ts);

CREATE TABLE IF NOT EXISTS exits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    exit_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    exit_time TEXT NOT NULL,
    reason TEXT NOT NULL,
    pnl REAL NOT NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE TABLE IF NOT EXISTS channel_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    channel_name TEXT,
    message_text TEXT NOT NULL,
    parse_result TEXT NOT NULL,
    trade_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_msg_time ON channel_messages(received_at);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,              -- ENTERED, EXITED, SKIPPED, CANCELLED, ERROR, INFO
    tradingsymbol TEXT,
    trade_id INTEGER,
    message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(ts);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    channel_name TEXT,
    raw_text TEXT NOT NULL,
    status TEXT NOT NULL,             -- RECEIVED, PARSED, VALIDATED, EXECUTED,
                                       -- CLOSED, REJECTED, DUPLICATE, INVALID,
                                       -- CANCELLED
    reject_reason TEXT,
    parsed_json TEXT,                 -- the ParsedSignal fields, for raw-vs-
                                       -- parsed inspection on the Signals screen
    trade_id INTEGER                  -- the trade this signal produced, amended,
                                       -- or (for DUPLICATE) was a repost of
);

CREATE INDEX IF NOT EXISTS idx_signal_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signal_trade ON signals(trade_id);
CREATE INDEX IF NOT EXISTS idx_signal_received ON signals(received_at);

CREATE TABLE IF NOT EXISTS bot_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,              -- INFO, WARNING, ERROR, DEBUG
    category TEXT NOT NULL,           -- ENTERED, EXITED, CANCELLED, SKIPPED, ERROR, INFO
    message TEXT NOT NULL,
    data_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_bot_event_time ON bot_events(ts);
CREATE INDEX IF NOT EXISTS idx_bot_event_level ON bot_events(level);

CREATE TABLE IF NOT EXISTS candle_cache (
    exchange TEXT NOT NULL,
    token TEXT NOT NULL,
    interval TEXT NOT NULL,
    candle_ts TEXT NOT NULL,
    o REAL NOT NULL,
    h REAL NOT NULL,
    l REAL NOT NULL,
    c REAL NOT NULL,
    v REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (exchange, token, interval, candle_ts)
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS won't add
# them to a database that already exists, so they're applied separately.
MIGRATIONS = [
    ("trades", "exit_order_id", "TEXT"),
    ("trades", "sl_order_id", "TEXT"),
    ("trades", "targets_provisional", "INTEGER DEFAULT 0"),
    ("trades", "current_ltp", "REAL"),
    ("trades", "ltp_updated_at", "TEXT"),
    ("trades", "trailing_sl", "REAL"),
    ("trades", "peak_ltp", "REAL"),
    # instrument_token/instrument_ticksize: lets the price-monitor loop skip
    # re-resolving the instrument (a full scan of the 169k-row master) on
    # every single polling cycle for trades created after this migration.
    # Rows from before it keep NULL here and fall back to the old lookup --
    # see TradeManager._tick().
    ("trades", "instrument_token", "TEXT"),
    ("trades", "instrument_ticksize", "REAL"),
    # Which signals row produced/amended this trade, so its lifecycle status
    # can be advanced (VALIDATED -> EXECUTED -> CLOSED) as the trade itself
    # moves through those same transitions.
    ("trades", "signal_id", "INTEGER"),
    # Fees are not modelled anywhere yet (paper_trading.calculate_pnl ignores
    # them) -- this column exists so "net P&L" has somewhere honest to live
    # once a charge model is configured, instead of silently equalling gross.
    ("trades", "charges", "REAL DEFAULT 0"),
]


def init_db():
    """Create tables if they don't exist, then apply any pending migrations."""
    with connect() as c:
        c.executescript(SCHEMA)
        c.execute("PRAGMA journal_mode=WAL")
        for table, column, coltype in MIGRATIONS:
            existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def insert_trade(trade: Dict[str, Any]) -> int:
    """Insert a new trade. Returns the new trade ID."""
    with connect() as c:
        cur = c.execute(
            """
            INSERT INTO trades (
                created_at, mode, symbol, tradingsymbol, exchange, option_type,
                strike, expiry, action, quantity, lot_size,
                entry_condition, entry_trigger, stoploss, targets,
                status, raw_signal, targets_provisional,
                instrument_token, instrument_ticksize, signal_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                trade["mode"],
                trade["symbol"],
                trade["tradingsymbol"],
                trade["exchange"],
                trade["option_type"],
                trade["strike"],
                trade["expiry"],
                trade["action"],
                trade["quantity"],
                trade["lot_size"],
                trade["entry_condition"],
                trade["entry_trigger"],
                trade["stoploss"],
                json.dumps(trade["targets"]),
                "PENDING",
                trade["raw_signal"],
                1 if trade.get("targets_provisional") else 0,
                trade.get("instrument_token"),
                trade.get("instrument_ticksize"),
                trade.get("signal_id"),
            ),
        )
        return cur.lastrowid


def mark_entered(trade_id: int, fill_price: float, broker_order_id: Optional[str] = None):
    with connect() as c:
        c.execute(
            """
            UPDATE trades
            SET status = 'ACTIVE', entry_price = ?, entry_time = ?, broker_order_id = ?
            WHERE id = ? AND status = 'PENDING'
            """,
            (fill_price, datetime.now().isoformat(timespec="seconds"), broker_order_id, trade_id),
        )


def mark_exited(trade_id: int, exit_price: float, reason: str, pnl: float,
                exit_order_id: Optional[str] = None):
    with connect() as c:
        cur = c.execute(
            """
            UPDATE trades
            SET status = 'CLOSED', exit_price = ?, exit_time = ?, exit_reason = ?,
                pnl = ?, exit_order_id = ?
            WHERE id = ? AND status = 'ACTIVE'
            """,
            (exit_price, datetime.now().isoformat(timespec="seconds"), reason, pnl,
             exit_order_id, trade_id),
        )
        if cur.rowcount == 0:
            # Already CLOSED/CANCELLED -- a concurrent tick beat us to it.
            # Don't log a second exit against the same position.
            return False

        c.execute(
            """
            INSERT INTO exits (trade_id, exit_price, quantity, exit_time, reason, pnl)
            SELECT id, ?, quantity, ?, ?, ?
            FROM trades WHERE id = ?
            """,
            (exit_price, datetime.now().isoformat(timespec="seconds"), reason, pnl, trade_id),
        )
        return True


def update_targets(trade_id: int, targets: List[float]) -> bool:
    """
    Replace the targets on a still-open trade.

    Used when the channel posts the target as a follow-up to the signal, which
    arrives after the trade has already been registered with a provisional
    (invented) target. Only touches PENDING/ACTIVE trades -- a closed trade's
    exit reason must keep referring to the targets it was actually judged on.
    """
    with connect() as c:
        cur = c.execute(
            """
            UPDATE trades SET targets = ?, targets_provisional = 0
            WHERE id = ? AND status IN ('PENDING', 'ACTIVE')
            """,
            (json.dumps(targets), trade_id),
        )
        return cur.rowcount > 0


def get_latest_awaiting_targets(within_minutes: float = 30.0) -> Optional[Dict[str, Any]]:
    """
    The most recent open trade still carrying invented targets.

    Fallback for when the channel posts its target line as a plain follow-up
    instead of a quoted reply, so there is no message link to follow. Limited
    to a recent window so a target line can't attach itself to a stale trade.
    """
    cutoff = datetime.now() - timedelta(minutes=within_minutes)
    with connect() as c:
        rows = c.execute(
            """
            SELECT * FROM trades
            WHERE status IN ('PENDING', 'ACTIVE') AND targets_provisional = 1
            ORDER BY id DESC
            """
        ).fetchall()

    for row in rows:
        t = _row_to_dict(row)
        try:
            if datetime.fromisoformat(t["created_at"]) >= cutoff:
                return t
        except (ValueError, TypeError):
            continue
    return None


def find_by_raw_signal(raw: str) -> Optional[Dict[str, Any]]:
    """The open trade created from this exact message text, if any."""
    with connect() as c:
        row = c.execute(
            """
            SELECT * FROM trades
            WHERE raw_signal = ? AND status IN ('PENDING', 'ACTIVE')
            ORDER BY id DESC LIMIT 1
            """,
            (raw,),
        ).fetchone()
        return _row_to_dict(row) if row else None


def update_ltp(trade_id: int, ltp: float):
    """Write the latest market price so the dashboard can show unrealized P&L."""
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as c:
        c.execute(
            "UPDATE trades SET current_ltp = ?, ltp_updated_at = ? WHERE id = ?",
            (ltp, now, trade_id),
        )
        c.execute(
            "INSERT INTO tick_history (trade_id, ltp, ts) VALUES (?, ?, ?)",
            (trade_id, ltp, now),
        )


def bulk_update_ltp(updates: List[tuple]):
    """Batch LTP writes + tick history: [(trade_id, ltp), ...]."""
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as c:
        c.executemany(
            "UPDATE trades SET current_ltp = ?, ltp_updated_at = ? WHERE id = ?",
            [(ltp, now, tid) for tid, ltp in updates],
        )
        c.executemany(
            "INSERT INTO tick_history (trade_id, ltp, ts) VALUES (?, ?, ?)",
            [(tid, ltp, now) for tid, ltp in updates],
        )


def get_tick_history(trade_id: int, limit: int = 500) -> List[Dict[str, Any]]:
    """Recent price ticks for a trade, oldest first."""
    with connect() as c:
        rows = c.execute(
            "SELECT ltp, ts FROM tick_history WHERE trade_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (trade_id, limit),
        ).fetchall()
    return [{"ltp": r["ltp"], "ts": r["ts"]} for r in reversed(rows)]


def update_trailing_sl(trade_id: int, trailing_sl: float, peak_ltp: float):
    """Move the trailing stoploss up (for BUY) or down (for SELL)."""
    with connect() as c:
        c.execute(
            "UPDATE trades SET trailing_sl = ?, peak_ltp = ? WHERE id = ?",
            (trailing_sl, peak_ltp, trade_id),
        )


def set_sl_order(trade_id: int, sl_order_id: Optional[str]):
    """Record (or clear, with None) the resting stoploss order at the exchange."""
    with connect() as c:
        c.execute("UPDATE trades SET sl_order_id = ? WHERE id = ?",
                  (sl_order_id, trade_id))


def find_open_duplicate(tradingsymbol: str, action: str,
                        entry_trigger: float) -> Optional[Dict[str, Any]]:
    """
    An already-open trade for the same instrument, side and trigger.

    Signal channels routinely repost or edit a signal, and Telethon delivers
    each as a new message. Without this check the same call opened a second
    position every time it was reposted.
    """
    with connect() as c:
        row = c.execute(
            """
            SELECT * FROM trades
            WHERE tradingsymbol = ? AND action = ? AND entry_trigger = ?
              AND status IN ('PENDING', 'ACTIVE')
            ORDER BY id DESC LIMIT 1
            """,
            (tradingsymbol, action, entry_trigger),
        ).fetchone()
        return _row_to_dict(row) if row else None


def expire_stale_pending(ttl_hours: float) -> List[Dict[str, Any]]:
    """
    Cancel PENDING trades whose trigger never came, or whose contract has
    expired. Returns the trades that were cancelled.

    Without this, an untriggered signal sits PENDING forever and keeps
    counting against MAX_OPEN_POSITIONS -- so after a few signals that never
    filled, the bot silently stopped taking every future signal.
    """
    now = datetime.now()
    cancelled = []

    for t in get_pending_trades():
        reason = None

        try:
            age_h = (now - datetime.fromisoformat(t["created_at"])).total_seconds() / 3600
            if age_h > ttl_hours:
                reason = f"not triggered within {ttl_hours}h"
        except (ValueError, TypeError):
            pass

        if reason is None:
            try:
                exp = datetime.strptime(t["expiry"], "%d-%b-%Y")
                if now.date() > exp.date():
                    reason = f"contract expired {t['expiry']}"
            except (ValueError, TypeError):
                pass

        if reason:
            mark_cancelled(t["id"], reason)
            t["notes"] = reason
            cancelled.append(t)

    return cancelled


def mark_cancelled(trade_id: int, reason: str = "manual"):
    with connect() as c:
        c.execute(
            "UPDATE trades SET status = 'CANCELLED', notes = ? WHERE id = ?",
            (reason, trade_id),
        )


def get_trade(trade_id: int) -> Optional[Dict[str, Any]]:
    with connect() as c:
        row = c.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        return _row_to_dict(row) if row else None


def get_trade_source(trade_id: int) -> Optional[Dict[str, Any]]:
    """
    The trade together with the signal and raw channel message that
    produced it, so "what did the channel actually say for this trade"
    is one lookup instead of cross-referencing trades/signals/channel_messages
    by hand.

    channel_messages.trade_id is the authoritative link to the message as
    actually received (it is what the parser saw, reply-quote stitching
    included); trades.signal_id is used only as a fallback for trades
    opened before that column existed.
    """
    trade = get_trade(trade_id)
    if trade is None:
        return None

    with connect() as c:
        message_row = c.execute(
            "SELECT * FROM channel_messages WHERE trade_id = ? ORDER BY id LIMIT 1",
            (trade_id,),
        ).fetchone()

    signal = None
    signal_id = trade.get("signal_id")
    if signal_id is not None:
        signal = get_signal(signal_id)
    elif message_row is not None:
        with connect() as c:
            sig_row = c.execute(
                "SELECT * FROM signals WHERE trade_id = ? ORDER BY id LIMIT 1",
                (trade_id,),
            ).fetchone()
        signal = _signal_row_to_dict(sig_row) if sig_row else None

    return {
        "trade": trade,
        "signal": signal,
        "message": dict(message_row) if message_row else None,
    }


def get_pending_trades() -> List[Dict[str, Any]]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM trades WHERE status = 'PENDING' ORDER BY id"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_active_trades() -> List[Dict[str, Any]]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM trades WHERE status = 'ACTIVE' ORDER BY id"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_open_trades() -> List[Dict[str, Any]]:
    """Pending + Active trades."""
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM trades WHERE status IN ('PENDING', 'ACTIVE') ORDER BY id"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_todays_stats(mode: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate stats for trades created today."""
    today = datetime.now().strftime("%Y-%m-%d")
    with connect() as c:
        q = (
            "SELECT "
            "  COUNT(*) AS total, "
            "  COALESCE(SUM(CASE WHEN status = 'CLOSED' AND pnl > 0 THEN 1 ELSE 0 END), 0) AS wins, "
            "  COALESCE(SUM(CASE WHEN status = 'CLOSED' AND pnl < 0 THEN 1 ELSE 0 END), 0) AS losses, "
            "  COALESCE(SUM(pnl), 0) AS total_pnl "
            "FROM trades WHERE DATE(created_at) = ? "
        )
        params = [today]
        if mode:
            q += " AND mode = ?"
            params.append(mode)
        row = c.execute(q, params).fetchone()
        return dict(row) if row else {}


def insert_message(channel_name: str, message_text: str, parse_result: str,
                   trade_id: Optional[int] = None,
                   received_at: Optional[datetime] = None) -> int:
    """
    received_at should be Telegram's own message timestamp (event.message.date /
    msg.date), not time.now() -- using processing time instead of post time is
    what made the Channel Feed's timing drift from the real channel during any
    catch-up or processing lag. Falls back to now() only when no Telegram
    timestamp is available.

    Returns the new row's id, so a caller that doesn't know the trade yet at
    insert time (the usual case: the message is parsed before any trade
    exists) can link it afterwards with update_message_trade().
    """
    if received_at is not None:
        stamp = received_at.astimezone().isoformat(timespec="seconds")
    else:
        stamp = datetime.now().isoformat(timespec="seconds")
    with connect() as c:
        cur = c.execute(
            """INSERT INTO channel_messages
               (received_at, channel_name, message_text, parse_result, trade_id)
               VALUES (?, ?, ?, ?, ?)""",
            (stamp, channel_name, message_text[:2000], parse_result, trade_id),
        )
        return cur.lastrowid


def update_message_trade(message_id: int, trade_id: int) -> None:
    """Link a channel message to the trade it ultimately produced or amended."""
    with connect() as c:
        c.execute(
            "UPDATE channel_messages SET trade_id = ? WHERE id = ?",
            (trade_id, message_id),
        )


def get_recent_messages(limit: int = 50) -> List[Dict[str, Any]]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM channel_messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def log_activity(level: str, message: str, tradingsymbol: Optional[str] = None,
                 trade_id: Optional[int] = None):
    """
    Record one line of the trade lifecycle -- entered, exited, skipped,
    cancelled, errored -- so the dashboard can show a running log instead of
    only the latest state of each trade.
    """
    with connect() as c:
        c.execute(
            """INSERT INTO activity_log (ts, level, tradingsymbol, trade_id, message)
               VALUES (?, ?, ?, ?, ?)""",
            (datetime.now().isoformat(timespec="seconds"),
             level, tradingsymbol, trade_id, message[:2000]),
        )


def get_recent_activity(limit: int = 100) -> List[Dict[str, Any]]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- bot_events
# Typed replacement for activity_log's string-sniffed level. activity_log
# keeps being written exactly as before (the legacy dashboard reads it); this
# is an additional, structured record aimed at the new API/UI.

def log_bot_event(level: str, category: str, message: str,
                  data: Optional[Dict[str, Any]] = None) -> int:
    with connect() as c:
        cur = c.execute(
            """INSERT INTO bot_events (ts, level, category, message, data_json)
               VALUES (?, ?, ?, ?, ?)""",
            (datetime.now().isoformat(timespec="seconds"), level, category,
             message[:2000], json.dumps(data) if data is not None else None),
        )
        return cur.lastrowid


def get_recent_bot_events(limit: int = 100, level: Optional[str] = None,
                          since: Optional[str] = None) -> List[Dict[str, Any]]:
    q = "SELECT * FROM bot_events WHERE 1=1"
    params: list = []
    if level:
        q += " AND level = ?"
        params.append(level.upper())
    if since:
        q += " AND ts >= ?"
        params.append(since)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with connect() as c:
        rows = c.execute(q, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("data_json"):
            try:
                d["data_json"] = json.loads(d["data_json"])
            except Exception:
                pass
        out.append(d)
    return out


# ---------------------------------------------------------------- signals
# One row per plausible signal attempt (a message that at least looked like
# it might be a trading call). Pure chatter never gets a row here -- that's
# what channel_messages' "ignored"/"skipped" parse_result already covers.
#
# status moves through: RECEIVED -> PARSED -> VALIDATED -> EXECUTED -> CLOSED,
# with REJECTED / DUPLICATE / INVALID / CANCELLED as the off-ramps. See
# telegram_listener.py and trade_manager.py for exactly where each transition
# is written.

def insert_signal(raw_text: str, status: str, channel_name: Optional[str] = None,
                  received_at: Optional[datetime] = None,
                  reject_reason: Optional[str] = None,
                  parsed_json: Optional[str] = None,
                  trade_id: Optional[int] = None) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    stamp = received_at.astimezone().isoformat(timespec="seconds") if received_at is not None else now
    with connect() as c:
        cur = c.execute(
            """INSERT INTO signals
               (created_at, received_at, channel_name, raw_text, status,
                reject_reason, parsed_json, trade_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, stamp, channel_name, raw_text[:2000], status,
             reject_reason, parsed_json, trade_id),
        )
        return cur.lastrowid


def update_signal(signal_id: int, status: str,
                  reject_reason: Optional[str] = None,
                  trade_id: Optional[int] = None,
                  parsed_json: Optional[str] = None) -> bool:
    """
    Advance a signal's lifecycle status.

    Only `status` is required; the other fields are set when provided and
    otherwise left untouched (COALESCE keeps the existing value) -- most
    transitions only need to change the status, e.g. "trade activated" never
    needs to re-supply a reject_reason that was never set in the first place.
    """
    with connect() as c:
        cur = c.execute(
            """UPDATE signals
               SET status = ?,
                   reject_reason = COALESCE(?, reject_reason),
                   trade_id = COALESCE(?, trade_id),
                   parsed_json = COALESCE(?, parsed_json)
               WHERE id = ?""",
            (status, reject_reason, trade_id, parsed_json, signal_id),
        )
        return cur.rowcount > 0


def get_signal(signal_id: int) -> Optional[Dict[str, Any]]:
    with connect() as c:
        row = c.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
    return _signal_row_to_dict(row) if row else None


def get_signals(status: Optional[str] = None, trade_id: Optional[int] = None,
                limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    q = "SELECT * FROM signals WHERE 1=1"
    params: list = []
    if status:
        q += " AND status = ?"
        params.append(status.upper())
    if trade_id is not None:
        q += " AND trade_id = ?"
        params.append(trade_id)
    q += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with connect() as c:
        rows = c.execute(q, params).fetchall()
    return [_signal_row_to_dict(r) for r in rows]


def _signal_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    if d.get("parsed_json"):
        try:
            d["parsed_json"] = json.loads(d["parsed_json"])
        except Exception:
            pass
    return d


# ---------------------------------------------------------------- overview / listing

def get_alltime_stats(mode: Optional[str] = None) -> Dict[str, Any]:
    """
    All-time aggregates over CLOSED trades: counts, realized P&L, and the
    gross profit/gross loss split a profit-factor calculation needs.
    """
    q = (
        "SELECT "
        "  COUNT(*) AS total, "
        "  COALESCE(SUM(CASE WHEN status = 'CLOSED' AND pnl > 0 THEN 1 ELSE 0 END), 0) AS wins, "
        "  COALESCE(SUM(CASE WHEN status = 'CLOSED' AND pnl < 0 THEN 1 ELSE 0 END), 0) AS losses, "
        "  COALESCE(SUM(CASE WHEN status = 'CLOSED' THEN pnl ELSE 0 END), 0) AS realized_pnl, "
        "  COALESCE(SUM(CASE WHEN status = 'CLOSED' AND pnl > 0 THEN pnl ELSE 0 END), 0) AS gross_profit, "
        "  COALESCE(SUM(CASE WHEN status = 'CLOSED' AND pnl < 0 THEN -pnl ELSE 0 END), 0) AS gross_loss, "
        "  COALESCE(SUM(CASE WHEN status = 'CLOSED' THEN charges ELSE 0 END), 0) AS total_charges "
        "FROM trades WHERE 1=1 "
    )
    params = []
    if mode:
        q += " AND mode = ?"
        params.append(mode)
    with connect() as c:
        row = c.execute(q, params).fetchone()
    return dict(row) if row else {}


def list_trades(status: Optional[str] = None, instrument: Optional[str] = None,
                profitable: Optional[bool] = None,
                date_from: Optional[str] = None, date_to: Optional[str] = None,
                page: int = 1, page_size: int = 25,
                sort: str = "id_desc") -> Dict[str, Any]:
    """Paginated, filtered trade history. Returns {items, total, page, page_size}."""
    where = ["1=1"]
    params: list = []

    if status:
        where.append("status = ?")
        params.append(status.upper())
    if instrument:
        where.append("(tradingsymbol LIKE ? OR symbol LIKE ?)")
        params.extend([f"%{instrument}%", f"%{instrument}%"])
    if profitable is True:
        where.append("pnl > 0")
    elif profitable is False:
        where.append("pnl < 0")
    if date_from:
        where.append("DATE(created_at) >= ?")
        params.append(date_from)
    if date_to:
        where.append("DATE(created_at) <= ?")
        params.append(date_to)

    where_sql = " AND ".join(where)

    sort_map = {
        "id_desc": "id DESC",
        "id_asc": "id ASC",
        "pnl_desc": "pnl DESC",
        "pnl_asc": "pnl ASC",
        "created_desc": "created_at DESC",
        "created_asc": "created_at ASC",
    }
    order_sql = sort_map.get(sort, "id DESC")

    page = max(page, 1)
    page_size = max(min(page_size, 200), 1)
    offset = (page - 1) * page_size

    with connect() as c:
        total = c.execute(f"SELECT COUNT(*) FROM trades WHERE {where_sql}", params).fetchone()[0]
        rows = c.execute(
            f"SELECT * FROM trades WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_analytics(date_from: Optional[str] = None, date_to: Optional[str] = None,
                   mode: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    Realized-P&L analytics over CLOSED trades, filtered by date range (on
    created_at, matching list_trades), mode ('paper'/'live'), and underlying
    symbol -- plus the distinct symbol list the filter UI offers, which is
    never itself filtered (otherwise picking a symbol would make every other
    symbol disappear from the dropdown).
    """
    where = ["status = 'CLOSED'"]
    params: list = []
    if date_from:
        where.append("DATE(created_at) >= ?")
        params.append(date_from)
    if date_to:
        where.append("DATE(created_at) <= ?")
        params.append(date_to)
    if mode:
        where.append("mode = ?")
        params.append(mode)
    if symbol:
        where.append("symbol = ?")
        params.append(symbol)
    where_sql = " AND ".join(where)
    net_pnl_sql = "(pnl - COALESCE(charges, 0))"

    with connect() as c:
        summary = c.execute(
            f"""
            SELECT
              COUNT(*) AS total_trades,
              COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
              COALESCE(SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), 0) AS losses,
              COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) AS gross_profit,
              COALESCE(SUM(CASE WHEN pnl < 0 THEN -pnl ELSE 0 END), 0) AS gross_loss,
              COALESCE(SUM(charges), 0) AS total_charges,
              COALESCE(SUM({net_pnl_sql}), 0) AS net_pnl
            FROM trades WHERE {where_sql}
            """, params,
        ).fetchone()

        by_day = c.execute(
            f"""
            SELECT DATE(created_at) AS day,
                   COUNT(*) AS trades,
                   COALESCE(SUM({net_pnl_sql}), 0) AS net_pnl
            FROM trades WHERE {where_sql}
            GROUP BY day ORDER BY day ASC
            """, params,
        ).fetchall()

        by_symbol = c.execute(
            f"""
            SELECT symbol,
                   COUNT(*) AS trades,
                   COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                   COALESCE(SUM({net_pnl_sql}), 0) AS net_pnl
            FROM trades WHERE {where_sql}
            GROUP BY symbol ORDER BY net_pnl DESC
            """, params,
        ).fetchall()

        symbols = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM trades ORDER BY symbol")]

    wins = summary["wins"]
    losses = summary["losses"]
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else None
    gross_profit = summary["gross_profit"] or 0
    gross_loss = summary["gross_loss"] or 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    return {
        "total_trades": summary["total_trades"],
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "total_charges": summary["total_charges"],
        "net_pnl": summary["net_pnl"],
        "by_day": [{"day": r["day"], "trades": r["trades"], "net_pnl": r["net_pnl"]} for r in by_day],
        "by_symbol": [
            {"symbol": r["symbol"], "trades": r["trades"], "wins": r["wins"], "net_pnl": r["net_pnl"]}
            for r in by_symbol
        ],
        "symbols": symbols,
    }


def list_signals(status: Optional[str] = None, date_from: Optional[str] = None,
                  date_to: Optional[str] = None, page: int = 1, page_size: int = 25) -> Dict[str, Any]:
    """Paginated, filtered signal inflow (received_at date range). Returns {items, total, page, page_size}."""
    where = ["1=1"]
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status.upper())
    if date_from:
        where.append("DATE(received_at) >= ?")
        params.append(date_from)
    if date_to:
        where.append("DATE(received_at) <= ?")
        params.append(date_to)
    where_sql = " AND ".join(where)

    page = max(page, 1)
    page_size = max(min(page_size, 200), 1)
    offset = (page - 1) * page_size

    with connect() as c:
        total = c.execute(f"SELECT COUNT(*) FROM signals WHERE {where_sql}", params).fetchone()[0]
        rows = c.execute(
            f"SELECT * FROM signals WHERE {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

    return {
        "items": [_signal_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_exits_for_trade(trade_id: int) -> List[Dict[str, Any]]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM exits WHERE trade_id = ? ORDER BY id", (trade_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- candle_cache

def get_cached_candles(exchange: str, token: str, interval: str,
                       from_ts: str, to_ts: str) -> List[Dict[str, Any]]:
    """Cached candles for (exchange, token, interval) within [from_ts, to_ts], oldest first."""
    with connect() as c:
        rows = c.execute(
            """SELECT candle_ts, o, h, l, c, v FROM candle_cache
               WHERE exchange = ? AND token = ? AND interval = ?
                 AND candle_ts >= ? AND candle_ts <= ?
               ORDER BY candle_ts""",
            (exchange, token, interval, from_ts, to_ts),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_candles(exchange: str, token: str, interval: str,
                   candles: List[Dict[str, Any]]) -> None:
    """
    Write fetched candles into the cache. candles: [{ts, o, h, l, c, v}, ...].
    A later fetch covering the same candle_ts overwrites it (a broker refetch
    of a partially-formed final candle should win over a stale cached one).
    """
    if not candles:
        return
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as c:
        c.executemany(
            """INSERT INTO candle_cache (exchange, token, interval, candle_ts, o, h, l, c, v, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(exchange, token, interval, candle_ts)
               DO UPDATE SET o=excluded.o, h=excluded.h, l=excluded.l, c=excluded.c,
                             v=excluded.v, fetched_at=excluded.fetched_at""",
            [
                (exchange, token, interval, cd["ts"], cd["o"], cd["h"], cd["l"],
                 cd["c"], cd.get("v"), now)
                for cd in candles
            ],
        )


# ---------------------------------------------------------------- tick fallback
# tick_history is keyed by trade_id, not by instrument -- there is no row at
# all for a token that was only ever watched, never traded. This join is
# only useful (and only claims to be) for a token that has instrument_token
# populated on at least one trade (Phase 1 migration; older trades have NULL
# here and are simply not found by this query).

def get_tick_history_for_token(exchange: str, token: str,
                               from_ts: Optional[str] = None,
                               to_ts: Optional[str] = None,
                               limit: int = 20000) -> List[Dict[str, Any]]:
    q = (
        "SELECT th.ltp, th.ts FROM tick_history th "
        "JOIN trades t ON t.id = th.trade_id "
        "WHERE t.exchange = ? AND t.instrument_token = ?"
    )
    params: list = [exchange, token]
    if from_ts:
        q += " AND th.ts >= ?"
        params.append(from_ts)
    if to_ts:
        q += " AND th.ts <= ?"
        params.append(to_ts)
    q += " ORDER BY th.ts LIMIT ?"
    params.append(limit)
    with connect() as c:
        rows = c.execute(q, params).fetchall()
    return [{"ltp": r["ltp"], "ts": r["ts"]} for r in rows]


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    if d.get("targets"):
        try:
            d["targets"] = json.loads(d["targets"])
        except Exception:
            pass
    return d
