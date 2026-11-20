"""Pydantic response models."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ConnectionStatus(BaseModel):
    connected: bool
    detail: Optional[str] = None


class BotStatus(BaseModel):
    mode: str                      # "paper" | "live" — drives the UI's permanent badge
    paused: bool
    uptime_seconds: float
    started_at: str                # ISO

    telegram: ConnectionStatus
    angel_broker: ConnectionStatus
    market_feed: ConnectionStatus  # AngelTicker WS

    last_signal_at: Optional[str] = None
    last_trade_at: Optional[str] = None
    last_tick_at: Optional[str] = None

    broker_errors: int
    telegram_errors: int
    last_error: Optional[str] = None
    last_error_at: Optional[str] = None


# ---------------------------------------------------------------- trades/positions

class TradeOut(BaseModel):
    id: int
    created_at: str
    mode: str
    symbol: str
    tradingsymbol: str
    exchange: str
    option_type: str
    strike: float
    expiry: str
    action: str
    quantity: int
    lot_size: int
    entry_condition: str
    entry_trigger: float
    entry_price: Optional[float] = None
    entry_time: Optional[str] = None
    stoploss: float
    targets: List[float] = []
    status: str
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    charges: Optional[float] = 0
    net_pnl: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    duration_seconds: Optional[float] = None
    broker_order_id: Optional[str] = None
    exit_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    targets_provisional: Optional[int] = 0
    current_ltp: Optional[float] = None
    ltp_updated_at: Optional[str] = None
    trailing_sl: Optional[float] = None
    peak_ltp: Optional[float] = None
    raw_signal: str
    notes: Optional[str] = None
    signal_id: Optional[int] = None
    instrument_token: Optional[str] = None


class ExitOut(BaseModel):
    id: int
    trade_id: int
    exit_price: float
    quantity: int
    exit_time: str
    reason: str
    pnl: float


class TradeDetail(BaseModel):
    trade: TradeOut
    exits: List[ExitOut] = []


class PaginatedTrades(BaseModel):
    items: List[TradeOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------- overview

class OverviewPeriod(BaseModel):
    total_trades: int
    wins: int
    losses: int
    realized_pnl: float


class OverviewResponse(BaseModel):
    today: OverviewPeriod
    all_time: OverviewPeriod
    gross_profit: float
    gross_loss: float
    net_pnl: float                 # realized - charges (all-time)
    win_rate: Optional[float] = None       # wins / (wins + losses), all-time CLOSED
    profit_factor: Optional[float] = None  # gross_profit / gross_loss
    active_positions: int
    pending_signals: int
    unrealized_pnl: float
    capital_deployed: float
    as_of: str


# ---------------------------------------------------------------- signals

class SignalOut(BaseModel):
    id: int
    created_at: str
    received_at: str
    channel_name: Optional[str] = None
    raw_text: str
    status: str
    reject_reason: Optional[str] = None
    parsed_json: Optional[Dict[str, Any]] = None
    trade_id: Optional[int] = None


class PaginatedSignals(BaseModel):
    items: List[SignalOut]
    total: int
    page: int
    page_size: int


class ChannelMessageOut(BaseModel):
    id: int
    received_at: str
    channel_name: Optional[str] = None
    message_text: str
    parse_result: str
    trade_id: Optional[int] = None


class TradeSource(BaseModel):
    trade: TradeOut
    signal: Optional[SignalOut] = None
    message: Optional[ChannelMessageOut] = None


# ---------------------------------------------------------------- analytics

class AnalyticsDayBucket(BaseModel):
    day: str
    trades: int
    net_pnl: float


class AnalyticsSymbolBucket(BaseModel):
    symbol: str
    trades: int
    wins: int
    net_pnl: float


class AnalyticsResponse(BaseModel):
    total_trades: int
    wins: int
    losses: int
    win_rate: Optional[float] = None
    gross_profit: float
    gross_loss: float
    profit_factor: Optional[float] = None
    total_charges: float
    net_pnl: float
    by_day: List[AnalyticsDayBucket] = []
    by_symbol: List[AnalyticsSymbolBucket] = []
    symbols: List[str] = []


# ---------------------------------------------------------------- market data

class InstrumentOut(BaseModel):
    token: str
    symbol: str
    name: Optional[str] = None
    exchange: str
    instrument_type: Optional[str] = None
    expiry: Optional[str] = None
    strike: float
    lotsize: int
    tick_size: float


class DepthLevel(BaseModel):
    price: Optional[float] = None
    quantity: Optional[float] = None
    orders: Optional[int] = None


class DepthOut(BaseModel):
    available: bool
    bid: List[Any] = []
    ask: List[Any] = []
    stale: Optional[bool] = None
    source: Optional[str] = None
    reason: Optional[str] = None


class QuoteOut(BaseModel):
    available: bool
    source: Optional[str] = None
    reason: Optional[str] = None
    stale: Optional[bool] = None
    ltp: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None
    volume: Optional[float] = None
    vwap: Optional[float] = None
    net_change: Optional[float] = None
    pct_change: Optional[float] = None
    depth: Optional[Dict[str, Any]] = None
    exch_feed_time: Optional[str] = None


class Candle(BaseModel):
    ts: str
    o: float
    h: float
    l: float
    c: float
    v: Optional[float] = None


class HistoryOut(BaseModel):
    available: bool
    source: Optional[str] = None
    reason: Optional[str] = None
    partial_last: bool = False
    candles: List[Candle] = []
