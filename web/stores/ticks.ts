/**
 * Live tick/candle state, kept OUT of the normal React render path.
 *
 * Raw WS messages write into a plain mutable buffer (zero React cost, can
 * arrive at any rate). A single requestAnimationFrame loop flushes that
 * buffer into the Zustand vanilla store at most once per frame, so even a
 * watchlist of 20 ticking instruments produces one batched store update per
 * frame instead of one per tick per instrument.
 *
 * The chart itself never reads this store through React at all -- it
 * subscribes directly via `ticksStore.subscribe()` in a useEffect and calls
 * the chart library's imperative update methods. Only small UI pieces (a
 * watchlist price cell, a position row's live P&L) use the `usePrice`/
 * `useCandleUpdate` hooks below, each scoped to exactly the key it needs so
 * unrelated ticks never re-render them.
 */
import { createStore, useStore } from "zustand";

export type PriceTick = { ltp: number; ts: number };
export type CandleUpdate = {
  exchange: string;
  token: string;
  interval: string;
  ts: string;
  o: number;
  h: number;
  l: number;
  c: number;
  closed: boolean;
};

type TicksState = {
  prices: Record<string, PriceTick>;
  candles: Record<string, CandleUpdate>; // key: `${token}:${interval}`
};

export const ticksStore = createStore<TicksState>(() => ({
  prices: {},
  candles: {},
}));

// ---------------------------------------------------------------- batched writes

const pendingPrices = new Map<string, PriceTick>();
const pendingCandles = new Map<string, CandleUpdate>();
let rafHandle: number | null = null;

function flush() {
  rafHandle = null;
  if (pendingPrices.size === 0 && pendingCandles.size === 0) return;

  const priceUpdates = Object.fromEntries(pendingPrices);
  const candleUpdates = Object.fromEntries(pendingCandles);
  pendingPrices.clear();
  pendingCandles.clear();

  ticksStore.setState((s) => ({
    prices: { ...s.prices, ...priceUpdates },
    candles: { ...s.candles, ...candleUpdates },
  }));
}

function scheduleFlush() {
  if (rafHandle !== null) return;
  rafHandle =
    typeof requestAnimationFrame === "function"
      ? requestAnimationFrame(flush)
      : (setTimeout(flush, 250) as unknown as number);
}

export function recordPrice(token: string, ltp: number): void {
  pendingPrices.set(token, { ltp, ts: Date.now() });
  scheduleFlush();
}

export function recordCandleUpdate(update: CandleUpdate): void {
  pendingCandles.set(`${update.token}:${update.interval}`, update);
  scheduleFlush();
}

// ---------------------------------------------------------------- scoped hooks

export function usePrice(token: string | undefined): PriceTick | undefined {
  return useStore(ticksStore, (s) => (token ? s.prices[token] : undefined));
}

export function useCandleUpdate(token: string | undefined, interval: string | undefined): CandleUpdate | undefined {
  return useStore(ticksStore, (s) => (token && interval ? s.candles[`${token}:${interval}`] : undefined));
}
