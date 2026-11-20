/**
 * Technical indicators computed client-side from the candle array already
 * on the chart. Pure functions, no chart-math dependency -- these are
 * standard, well-known formulas and the set is small enough not to justify
 * pulling in a library.
 *
 * Every function returns points aligned 1:1 with the input candles (using
 * `null` wherever the indicator isn't yet defined, e.g. the first
 * `period - 1` bars of an SMA) so callers can zip them against the same
 * time axis without re-deriving alignment.
 */
import type { Candle } from "./api";

export type IndicatorPoint = { time: number; value: number };

function toEpochSeconds(ts: string): number {
  return Math.floor(new Date(ts).getTime() / 1000);
}

function compact(times: number[], values: (number | null)[]): IndicatorPoint[] {
  const out: IndicatorPoint[] = [];
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v !== null && Number.isFinite(v)) out.push({ time: times[i], value: v });
  }
  return out;
}

export function sma(candles: Candle[], period: number): IndicatorPoint[] {
  const times = candles.map((c) => toEpochSeconds(c.ts));
  const values: (number | null)[] = new Array(candles.length).fill(null);
  let sum = 0;
  for (let i = 0; i < candles.length; i++) {
    sum += candles[i].c;
    if (i >= period) sum -= candles[i - period].c;
    if (i >= period - 1) values[i] = sum / period;
  }
  return compact(times, values);
}

export function ema(candles: Candle[], period: number): IndicatorPoint[] {
  const times = candles.map((c) => toEpochSeconds(c.ts));
  const values: (number | null)[] = new Array(candles.length).fill(null);
  if (candles.length < period) return [];

  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += candles[i].c;
  let prev = seed / period;
  values[period - 1] = prev;

  for (let i = period; i < candles.length; i++) {
    prev = candles[i].c * k + prev * (1 - k);
    values[i] = prev;
  }
  return compact(times, values);
}

/**
 * Session VWAP: cumulative(typical price * volume) / cumulative(volume),
 * typical price = (h+l+c)/3, reset at the start of the candle array (the
 * caller passes one session's worth of candles if a true session reset
 * matters).
 *
 * Requires every candle to carry real volume. Tick-derived candles
 * (MarketDataService's fallback path) never have volume -- ticks carry no
 * traded quantity -- so this returns [] in that case rather than computing
 * a VWAP against fabricated volume. Callers should hide the VWAP toggle
 * (or show it disabled) when this comes back empty.
 */
export function vwap(candles: Candle[]): IndicatorPoint[] {
  if (candles.length === 0 || candles.some((c) => c.v === null || c.v === undefined)) return [];
  const times = candles.map((c) => toEpochSeconds(c.ts));
  const values: number[] = [];
  let cumPV = 0;
  let cumV = 0;
  for (const c of candles) {
    const typical = (c.h + c.l + c.c) / 3;
    const v = c.v as number;
    cumPV += typical * v;
    cumV += v;
    values.push(cumV > 0 ? cumPV / cumV : typical);
  }
  return compact(times, values);
}

/** Wilder's RSI. */
export function rsi(candles: Candle[], period = 14): IndicatorPoint[] {
  const times = candles.map((c) => toEpochSeconds(c.ts));
  const values: (number | null)[] = new Array(candles.length).fill(null);
  if (candles.length <= period) return [];

  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i <= period; i++) {
    const change = candles[i].c - candles[i - 1].c;
    if (change > 0) gainSum += change;
    else lossSum -= change;
  }
  let avgGain = gainSum / period;
  let avgLoss = lossSum / period;
  values[period] = _rsiFromAverages(avgGain, avgLoss);

  for (let i = period + 1; i < candles.length; i++) {
    const change = candles[i].c - candles[i - 1].c;
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    values[i] = _rsiFromAverages(avgGain, avgLoss);
  }
  return compact(times, values);
}

function _rsiFromAverages(avgGain: number, avgLoss: number): number {
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

export type MacdResult = {
  macd: IndicatorPoint[];
  signal: IndicatorPoint[];
  histogram: IndicatorPoint[];
};

/** Standard 12/26/9 MACD. */
export function macd(candles: Candle[], fast = 12, slow = 26, signalPeriod = 9): MacdResult {
  if (candles.length < slow + signalPeriod) return { macd: [], signal: [], histogram: [] };

  const times = candles.map((c) => toEpochSeconds(c.ts));
  const fastEma = _emaSeries(candles.map((c) => c.c), fast);
  const slowEma = _emaSeries(candles.map((c) => c.c), slow);

  const macdLine: (number | null)[] = candles.map((_, i) => {
    const f = fastEma[i];
    const s = slowEma[i];
    return f !== null && s !== null ? f - s : null;
  });

  const firstValid = macdLine.findIndex((v) => v !== null);
  const signalInput = macdLine.slice(firstValid).map((v) => v as number);
  const signalEma = _emaSeriesFlat(signalInput, signalPeriod);

  const signalLine: (number | null)[] = new Array(candles.length).fill(null);
  const histogram: (number | null)[] = new Array(candles.length).fill(null);
  for (let i = 0; i < signalEma.length; i++) {
    const idx = firstValid + i;
    signalLine[idx] = signalEma[i];
    if (signalEma[i] !== null && macdLine[idx] !== null) {
      histogram[idx] = (macdLine[idx] as number) - (signalEma[i] as number);
    }
  }

  return {
    macd: compact(times, macdLine),
    signal: compact(times, signalLine),
    histogram: compact(times, histogram),
  };
}

function _emaSeries(closes: number[], period: number): (number | null)[] {
  const values: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period) return values;
  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += closes[i];
  let prev = seed / period;
  values[period - 1] = prev;
  for (let i = period; i < closes.length; i++) {
    prev = closes[i] * k + prev * (1 - k);
    values[i] = prev;
  }
  return values;
}

function _emaSeriesFlat(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period) return out;
  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i];
  let prev = seed / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}
