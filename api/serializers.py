"""
DB row -> API shape.

Every field a trade/signal response can expose is named explicitly here.
Nothing in this module ever reads config, os.environ, or a broker/session
object -- only the DB row dict it's given -- so there is no path by which a
credential could reach a response body through these functions. See
tests/test_serializers.py for the redaction test that checks this holds for
real, against live HTTP responses, not just by code inspection.
"""
from datetime import datetime
from typing import Any, Dict, Optional

import paper_trading

# Every field on the `trades` row that is safe and useful to expose. No
# column added to that table in the future reaches a response unless it's
# added here too.
_TRADE_FIELDS = (
    "id", "created_at", "mode", "symbol", "tradingsymbol", "exchange",
    "option_type", "strike", "expiry", "action", "quantity", "lot_size",
    "entry_condition", "entry_trigger", "entry_price", "entry_time",
    "stoploss", "targets", "status", "exit_price", "exit_time",
    "exit_reason", "pnl", "charges", "broker_order_id", "exit_order_id",
    "sl_order_id", "targets_provisional", "current_ltp", "ltp_updated_at",
    "trailing_sl", "peak_ltp", "raw_signal", "notes", "signal_id",
    # Not a secret -- just an instrument identifier. The frontend needs it
    # to correlate a WS CANDLE_UPDATE/tick (keyed by exchange+token) with the
    # REST position row it belongs to.
    "instrument_token",
)

_EXIT_FIELDS = ("id", "trade_id", "exit_price", "quantity", "exit_time", "reason", "pnl")

_SIGNAL_FIELDS = (
    "id", "created_at", "received_at", "channel_name", "raw_text", "status",
    "reject_reason", "parsed_json", "trade_id",
)

_CHANNEL_MESSAGE_FIELDS = (
    "id", "received_at", "channel_name", "message_text", "parse_result", "trade_id",
)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def serialize_trade(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    One trade/position, with two fields computed rather than stored:
      - duration_seconds: entry_time -> exit_time (or now, if still open)
      - unrealized_pnl: only set for ACTIVE trades, using the same
        paper_trading.calculate_pnl the engine itself uses for the real exit,
        against current_ltp. CLOSED trades use the stored `pnl` (realized);
        this field is None for them, not a stale snapshot.
      - net_pnl: pnl - charges. Charges are 0 until a charge model exists,
        so today net_pnl == pnl -- shown as its own field instead of silently
        reusing `pnl`, so the UI can label it accurately either way.
    """
    out = {k: row.get(k) for k in _TRADE_FIELDS}

    entry_time = _parse_iso(row.get("entry_time"))
    exit_time = _parse_iso(row.get("exit_time"))
    if entry_time:
        end = exit_time or datetime.now()
        out["duration_seconds"] = max((end - entry_time).total_seconds(), 0)
    else:
        out["duration_seconds"] = None

    out["unrealized_pnl"] = None
    if row.get("status") == "ACTIVE" and row.get("current_ltp") is not None:
        try:
            out["unrealized_pnl"] = paper_trading.calculate_pnl(row, row["current_ltp"])
        except Exception:
            out["unrealized_pnl"] = None

    pnl = row.get("pnl")
    charges = row.get("charges") or 0
    out["net_pnl"] = (pnl - charges) if pnl is not None else None

    return out


def serialize_exit(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: row.get(k) for k in _EXIT_FIELDS}


def serialize_signal(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: row.get(k) for k in _SIGNAL_FIELDS}


def serialize_channel_message(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: row.get(k) for k in _CHANNEL_MESSAGE_FIELDS}
