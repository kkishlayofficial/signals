/**
 * Typed client for the FastAPI dashboard API, called through the Next.js
 * proxy route (/api/proxy/...) so the bearer token never reaches the
 * browser. Types here mirror api/schemas.py and api/serializers.py in the
 * Python backend field-for-field -- kept by hand rather than generated,
 * since both sides are maintained together.
 */

// ---------------------------------------------------------------- types

export type ConnectionStatus = { connected: boolean; detail: string | null };

export type BotStatus = {
  mode: "paper" | "live";
  paused: boolean;
  uptime_seconds: number;
  started_at: string;
  telegram: ConnectionStatus;
  angel_broker: ConnectionStatus;
  market_feed: ConnectionStatus;
  last_signal_at: string | null;
  last_trade_at: string | null;
  last_tick_at: string | null;
  broker_errors: number;
  telegram_errors: number;
  last_error: string | null;
  last_error_at: string | null;
};

export type TradeStatus = "PENDING" | "ACTIVE" | "CLOSED" | "CANCELLED";

export type Trade = {
  id: number;
  created_at: string;
  mode: "paper" | "live";
  symbol: string;
  tradingsymbol: string;
  exchange: string;
  option_type: string;
  strike: number;
  expiry: string;
  action: "BUY" | "SELL";
  quantity: number;
  lot_size: number;
  entry_condition: "ABOVE" | "BELOW";
  entry_trigger: number;
  entry_price: number | null;
  entry_time: string | null;
  stoploss: number;
  targets: number[];
  status: TradeStatus;
  exit_price: number | null;
  exit_time: string | null;
  exit_reason: string | null;
  pnl: number | null;
  charges: number | null;
  net_pnl: number | null;
  unrealized_pnl: number | null;
  duration_seconds: number | null;
  broker_order_id: string | null;
  exit_order_id: string | null;
  sl_order_id: string | null;
  targets_provisional: number | null;
  current_ltp: number | null;
  ltp_updated_at: string | null;
  trailing_sl: number | null;
  peak_ltp: number | null;
  raw_signal: string;
  notes: string | null;
  signal_id: number | null;
  /** Not every trade has one -- only those created after the Phase 1
   *  migration. Used to correlate a live WS tick/candle (keyed by
   *  exchange+token) with this row. */
  instrument_token: string | null;
};

export type ExitRow = {
  id: number;
  trade_id: number;
  exit_price: number;
  quantity: number;
  exit_time: string;
  reason: string;
  pnl: number;
};

export type TradeDetail = { trade: Trade; exits: ExitRow[] };

export type PaginatedTrades = { items: Trade[]; total: number; page: number; page_size: number };

export type OverviewPeriod = { total_trades: number; wins: number; losses: number; realized_pnl: number };

export type Overview = {
  today: OverviewPeriod;
  all_time: OverviewPeriod;
  gross_profit: number;
  gross_loss: number;
  net_pnl: number;
  win_rate: number | null;
  profit_factor: number | null;
  active_positions: number;
  pending_signals: number;
  unrealized_pnl: number;
  capital_deployed: number;
  as_of: string;
};

export type SignalStatus =
  | "RECEIVED" | "PARSED" | "VALIDATED" | "EXECUTED" | "CLOSED"
  | "REJECTED" | "DUPLICATE" | "INVALID" | "CANCELLED";

export type Signal = {
  id: number;
  created_at: string;
  received_at: string;
  channel_name: string | null;
  raw_text: string;
  status: SignalStatus;
  reject_reason: string | null;
  parsed_json: Record<string, unknown> | null;
  trade_id: number | null;
};

export type PaginatedSignals = { items: Signal[]; total: number; page: number; page_size: number };

export type ChannelMessage = {
  id: number;
  received_at: string;
  channel_name: string | null;
  message_text: string;
  parse_result: string;
  trade_id: number | null;
};

export type TradeSource = { trade: Trade; signal: Signal | null; message: ChannelMessage | null };

export type AnalyticsDayBucket = { day: string; trades: number; net_pnl: number };
export type AnalyticsSymbolBucket = { symbol: string; trades: number; wins: number; net_pnl: number };

export type Analytics = {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  gross_profit: number;
  gross_loss: number;
  profit_factor: number | null;
  total_charges: number;
  net_pnl: number;
  by_day: AnalyticsDayBucket[];
  by_symbol: AnalyticsSymbolBucket[];
  symbols: string[];
};

export type Instrument = {
  token: string;
  symbol: string;
  name: string | null;
  exchange: string;
  instrument_type: string | null;
  expiry: string | null;
  strike: number;
  lotsize: number;
  tick_size: number;
};

export type DepthLevel = { price: number; quantity: number; orders: number };

export type Depth = {
  available: boolean;
  bid: DepthLevel[];
  ask: DepthLevel[];
  stale: boolean | null;
  source: string | null;
  reason: string | null;
};

export type Quote = {
  available: boolean;
  source: string | null;
  reason: string | null;
  stale: boolean | null;
  ltp: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
  volume: number | null;
  vwap: number | null;
  net_change: number | null;
  pct_change: number | null;
  depth: { bid: DepthLevel[]; ask: DepthLevel[]; available: boolean } | null;
  exch_feed_time: string | null;
};

export type Candle = { ts: string; o: number; h: number; l: number; c: number; v: number | null };

export type History = {
  available: boolean;
  source: "broker" | "ticks" | null;
  reason: string | null;
  partial_last: boolean;
  candles: Candle[];
};

export type Interval = "1m" | "3m" | "5m" | "15m" | "30m" | "1h" | "1d";

export type BotLogLevel = "INFO" | "WARNING" | "ERROR" | "DEBUG";

export type BotLogEntry = {
  id: number;
  ts: string;
  level: BotLogLevel;
  category: string;
  message: string;
  data_json: Record<string, unknown> | null;
};

// ---------------------------------------------------------------- client

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
  method: "GET" | "POST" = "GET",
): Promise<T> {
  const qs = params
    ? "?" +
      Object.entries(params)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";
  const res = await fetch(`/api/proxy/${path}${qs}`, { method, cache: "no-store" });
  if (!res.ok) {
    let message = `Request failed: ${res.status}`;
    try {
      const body = await res.json();
      message = body?.error?.message ?? body?.detail ?? message;
    } catch {
      // body wasn't JSON -- keep the generic message
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export const api = {
  botStatus: () => request<BotStatus>("bot/status"),
  overview: () => request<Overview>("dashboard/overview"),
  positions: () => request<Trade[]>("positions"),
  closePosition: (id: number) => request<Trade>(`positions/${id}/close`, undefined, "POST"),
  cancelPosition: (id: number) => request<Trade>(`positions/${id}/cancel`, undefined, "POST"),
  trades: (params: {
    status?: TradeStatus; instrument?: string; profitable?: boolean;
    date_from?: string; date_to?: string; page?: number; page_size?: number; sort?: string;
  }) => request<PaginatedTrades>("trades", params),
  tradeDetail: (id: number) => request<TradeDetail>(`trades/${id}`),
  tradeSource: (id: number) => request<TradeSource>(`trades/${id}/source`),
  signals: (params: {
    status?: SignalStatus; date_from?: string; date_to?: string; page?: number; page_size?: number;
  }) => request<PaginatedSignals>("signals", params),
  signalDetail: (id: number) => request<Signal>(`signals/${id}`),
  analytics: (params: {
    date_from?: string; date_to?: string; mode?: "paper" | "live"; symbol?: string;
  }) => request<Analytics>("analytics", params),
  searchInstruments: (q: string, exchange?: string, limit = 20) =>
    request<Instrument[]>("instruments", { q, exchange, limit }),
  instrument: (exchange: string, token: string) =>
    request<Instrument>(`instruments/${exchange}/${token}`),
  quote: (exchange: string, token: string) => request<Quote>(`market/quote/${exchange}/${token}`),
  depth: (exchange: string, token: string) => request<Depth>(`market/depth/${exchange}/${token}`),
  history: (exchange: string, token: string, interval: Interval, from?: string, to?: string) =>
    request<History>(`market/history/${exchange}/${token}`, { interval, from, to }),
  botLogs: (params?: { level?: BotLogLevel; limit?: number }) =>
    request<BotLogEntry[]>("bot/logs", params),
  pauseBot: () => request<BotStatus>("bot/pause", undefined, "POST"),
  resumeBot: () => request<BotStatus>("bot/resume", undefined, "POST"),
};

export async function mintWsTicket(): Promise<string> {
  const res = await fetch("/api/ws-ticket", { method: "POST", cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to mint WS ticket: ${res.status}`);
  const body = await res.json();
  return body.ticket as string;
}

export { ApiError };
