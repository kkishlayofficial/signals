/**
 * Mirrors paper_trading.calculate_pnl (Python) exactly, so the frontend can
 * show unrealized P&L the instant a live tick arrives, without waiting on
 * a REST round-trip. If the formula ever changes, change it in both places
 * -- there is deliberately no shared source between a Python backend and a
 * TypeScript frontend.
 */
export type PnlInput = {
  entry_price: number | null;
  entry_trigger: number;
  quantity: number;
  lot_size: number;
  action: "BUY" | "SELL";
};

export function calculatePnl(trade: PnlInput, exitPrice: number): number {
  const entry = trade.entry_price ?? trade.entry_trigger;
  const qty = trade.quantity * trade.lot_size;
  const raw = trade.action === "BUY" ? (exitPrice - entry) * qty : (entry - exitPrice) * qty;
  return Math.round(raw * 100) / 100;
}

const paperPnl = { calculatePnl };
export default paperPnl;
