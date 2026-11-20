"""
Paper trading engine.

Behaves identically to the live engine from the trade manager's point of view,
but no real orders are placed. Fill prices are simulated as the LTP at the
moment the entry trigger / SL / target is crossed.

All positions are still tracked in the SQLite database.
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import database as db

logger = logging.getLogger(__name__)


class PaperBroker:
    """A drop-in stand-in for AngelBroker in paper mode.

    It still needs *some* real LTP source to be useful, so we accept the real
    broker instance as a dependency for quote lookups. If no live broker is
    supplied, quotes return None and the caller must provide them.
    """

    def __init__(self, live_broker=None):
        self.live_broker = live_broker

    def get_ltp(self, exchange: str, tradingsymbol: str, token: str) -> Optional[float]:
        if self.live_broker is None:
            return None
        return self.live_broker.get_ltp(exchange, tradingsymbol, token)

    def place_limit_order(
        self,
        tradingsymbol: str,
        token: str,
        exchange: str,
        action: str,
        quantity: int,
        limit_price: float = 0,
        **kwargs,
    ) -> str:
        """Simulate a limit order — returns a synthetic order ID."""
        order_id = f"PAPER-LMT-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        logger.info(f"[PAPER] LIMIT {action} {quantity} {tradingsymbol} @ {limit_price} → {order_id}")
        return order_id

    def place_market_order(
        self,
        tradingsymbol: str,
        token: str,
        exchange: str,
        action: str,
        quantity: int,
        **kwargs,
    ) -> str:
        """Simulate a market order — returns a synthetic order ID."""
        order_id = f"PAPER-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        logger.info(f"[PAPER] MARKET {action} {quantity} {tradingsymbol} → {order_id}")
        return order_id


def calculate_pnl(trade: Dict[str, Any], exit_price: float) -> float:
    """Calculate P&L for a trade given the exit price. Fees ignored."""
    entry = trade.get("entry_price") or trade["entry_trigger"]
    qty = trade["quantity"] * trade["lot_size"]
    if trade["action"] == "BUY":
        return round((exit_price - entry) * qty, 2)
    else:
        return round((entry - exit_price) * qty, 2)


def check_trigger_hit(trade: Dict[str, Any], ltp: float) -> bool:
    """Has the entry trigger been crossed?"""
    if trade["entry_condition"] == "ABOVE":
        return ltp >= trade["entry_trigger"]
    return ltp <= trade["entry_trigger"]


def check_stoploss_hit(trade: Dict[str, Any], ltp: float) -> bool:
    """Has the stoploss been hit?"""
    if trade["action"] == "BUY":
        return ltp <= trade["stoploss"]
    return ltp >= trade["stoploss"]


def check_trailing_sl_hit(trade: Dict[str, Any], ltp: float) -> bool:
    """Has the trailing stoploss been hit?"""
    tsl = trade.get("trailing_sl")
    if tsl is None:
        return False
    if trade["action"] == "BUY":
        return ltp <= tsl
    return ltp >= tsl


def compute_trailing_sl(trade: Dict[str, Any], ltp: float,
                        trail_pct: float,
                        activation_target: Optional[float] = None) -> Optional[float]:
    """
    Calculate new trailing SL level given the current LTP.
    Returns None if trailing hasn't activated yet, or the new TSL level.

    activation_target: when given, trailing only starts once price has
    reached this level (the first target), rather than immediately.
    """
    is_buy = trade["action"] == "BUY"

    if activation_target is not None:
        if is_buy and ltp < activation_target:
            return None
        if not is_buy and ltp > activation_target:
            return None

    peak = trade.get("peak_ltp")
    if is_buy:
        peak = max(peak or ltp, ltp)
        new_tsl = peak * (1 - trail_pct / 100.0)
        old_tsl = trade.get("trailing_sl")
        if old_tsl is not None and new_tsl <= old_tsl:
            return None
    else:
        peak = min(peak or ltp, ltp)
        new_tsl = peak * (1 + trail_pct / 100.0)
        old_tsl = trade.get("trailing_sl")
        if old_tsl is not None and new_tsl >= old_tsl:
            return None

    return round(new_tsl, 2)


def check_target_hit(trade: Dict[str, Any], ltp: float) -> Optional[int]:
    """
    Which target (0-indexed) was hit? None if none.

    We exit on the first target. More sophisticated strategies could scale out.
    """
    targets = trade["targets"]
    if not targets:
        return None
    for i, tgt in enumerate(targets):
        if trade["action"] == "BUY" and ltp >= tgt:
            return i
        if trade["action"] == "SELL" and ltp <= tgt:
            return i
    return None
