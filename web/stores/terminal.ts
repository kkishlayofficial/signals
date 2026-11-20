import { create } from "zustand";
import type { Interval } from "@/lib/api";

export type SelectedInstrument = {
  exchange: string;
  token: string;
  symbol: string;
  name: string | null;
};

export type IndicatorToggles = {
  sma: boolean;
  smaPeriod: number;
  ema: boolean;
  emaPeriod: number;
  vwap: boolean;
  rsi: boolean;
  macd: boolean;
};

const DEFAULT_INDICATORS: IndicatorToggles = {
  sma: false,
  smaPeriod: 20,
  ema: false,
  emaPeriod: 20,
  vwap: false,
  rsi: false,
  macd: false,
};

type TerminalStore = {
  selected: SelectedInstrument | null;
  timeframe: Interval;
  indicators: IndicatorToggles;
  /** A trade id to highlight on the chart (entry/SL/target), set when a
   *  position row is clicked in the bottom tabs. */
  highlightedTradeId: number | null;

  selectInstrument: (inst: SelectedInstrument) => void;
  setTimeframe: (tf: Interval) => void;
  toggleIndicator: (key: "sma" | "ema" | "vwap" | "rsi" | "macd") => void;
  setIndicatorPeriod: (key: "smaPeriod" | "emaPeriod", period: number) => void;
  setHighlightedTrade: (id: number | null) => void;
};

export const useTerminalStore = create<TerminalStore>((set) => ({
  selected: null,
  timeframe: "5m",
  indicators: DEFAULT_INDICATORS,
  highlightedTradeId: null,

  selectInstrument: (inst) => set({ selected: inst, highlightedTradeId: null }),
  setTimeframe: (timeframe) => set({ timeframe }),
  toggleIndicator: (key) =>
    set((s) => ({ indicators: { ...s.indicators, [key]: !s.indicators[key] } })),
  setIndicatorPeriod: (key, period) =>
    set((s) => ({ indicators: { ...s.indicators, [key]: period } })),
  setHighlightedTrade: (highlightedTradeId) => set({ highlightedTradeId }),
}));
