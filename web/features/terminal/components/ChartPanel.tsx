"use client";

import { useEffect, useRef } from "react";
import {
  createChart, createSeriesMarkers, ColorType, CrosshairMode, LineStyle,
  CandlestickSeries, HistogramSeries, LineSeries,
  type IChartApi, type ISeriesApi, type UTCTimestamp, type SeriesMarker,
  type Time, type IPriceLine,
} from "lightweight-charts";
import { useTerminalStore } from "@/stores/terminal";
import { ticksStore } from "@/stores/ticks";
import { useHistory } from "../hooks/useHistory";
import { useTradesForInstrument } from "../hooks/useTradesForInstrument";
import { useInstrumentSubscription } from "../hooks/useInstrumentSubscription";
import { sma, ema, vwap, rsi, macd } from "@/lib/indicators";
import type { Candle } from "@/lib/api";

const BULL = "#26a69a";
const BEAR = "#ef5350";
const GRID = "#1e293b";
const AXIS_TEXT = "#94a3b8";

function toTime(ts: string): UTCTimestamp {
  return Math.floor(new Date(ts).getTime() / 1000) as UTCTimestamp;
}

type MacdRefs = {
  macd: ISeriesApi<"Line">;
  signal: ISeriesApi<"Line">;
  hist: ISeriesApi<"Histogram">;
};

export function ChartPanel() {
  const selected = useTerminalStore((s) => s.selected);
  const timeframe = useTerminalStore((s) => s.timeframe);
  const indicators = useTerminalStore((s) => s.indicators);
  const highlightedTradeId = useTerminalStore((s) => s.highlightedTradeId);

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlaySeriesRef = useRef<Record<string, ISeriesApi<"Line">>>({});
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSeriesRef = useRef<MacdRefs | null>(null);
  const markersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const candlesRef = useRef<Candle[]>([]);

  const history = useHistory(selected?.exchange, selected?.token, timeframe);
  const { trades } = useTradesForInstrument(selected?.exchange, selected?.token);
  useInstrumentSubscription(selected?.exchange, selected?.token, timeframe);

  // 1) Create the chart + its base series once; destroy on unmount.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#020617" }, textColor: AXIS_TEXT },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: GRID },
      rightPriceScale: { borderColor: GRID },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(
      CandlestickSeries,
      { upColor: BULL, downColor: BEAR, borderVisible: false, wickUpColor: BULL, wickDownColor: BEAR },
      0,
    );
    candleSeriesRef.current = candleSeries;

    const volumeSeries = chart.addSeries(
      HistogramSeries,
      { priceFormat: { type: "volume" }, priceScaleId: "volume-overlay", color: `${BULL}40` },
      0,
    );
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volumeSeriesRef.current = volumeSeries;

    markersRef.current = createSeriesMarkers<Time>(candleSeries, []);

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) chart.resize(entry.contentRect.width, entry.contentRect.height);
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      overlaySeriesRef.current = {};
      rsiSeriesRef.current = null;
      macdSeriesRef.current = null;
      markersRef.current = null;
      priceLinesRef.current = [];
    };
  }, []);

  // 2) Load fetched history whenever the instrument/timeframe/data changes.
  useEffect(() => {
    if (!candleSeriesRef.current || !history.data?.candles) return;
    const candles = history.data.candles;
    candlesRef.current = candles;
    candleSeriesRef.current.setData(
      candles.map((c) => ({ time: toTime(c.ts), open: c.o, high: c.h, low: c.l, close: c.c })),
    );
    volumeSeriesRef.current?.setData(
      candles.map((c) => ({
        time: toTime(c.ts), value: c.v ?? 0,
        color: c.c >= c.o ? `${BULL}66` : `${BEAR}66`,
      })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [history.data]);

  // 3) Live tail -- subscribed directly to the vanilla ticks store, never
  //    through React state/props, so a tick never triggers a React
  //    re-render of this component; only the chart library's own imperative
  //    `update()` call runs.
  useEffect(() => {
    if (!selected) return;
    const key = `${selected.token}:${timeframe}`;
    return ticksStore.subscribe((state, prev) => {
      const update = state.candles[key];
      if (!update || update === prev.candles[key] || !candleSeriesRef.current) return;
      candleSeriesRef.current.update({
        time: toTime(update.ts), open: update.o, high: update.h, low: update.l, close: update.c,
      });
    });
    // Deliberately keyed on selected?.token, not the `selected` object --
    // selectInstrument() always creates a fresh object whenever token
    // changes, so token already captures every case this effect needs to
    // re-run for, without resubscribing on an unrelated field change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.token, timeframe]);

  // 4) Overlay indicators (SMA/EMA/VWAP) on the main pane.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const candles = candlesRef.current;

    const desired: Record<string, { color: string; points: ReturnType<typeof sma> }> = {};
    if (indicators.sma && candles.length) desired.sma = { color: "#38bdf8", points: sma(candles, indicators.smaPeriod) };
    if (indicators.ema && candles.length) desired.ema = { color: "#f59e0b", points: ema(candles, indicators.emaPeriod) };
    if (indicators.vwap && candles.length) desired.vwap = { color: "#8b5cf6", points: vwap(candles) };

    for (const key of Object.keys(overlaySeriesRef.current)) {
      if (!desired[key]) {
        chart.removeSeries(overlaySeriesRef.current[key]);
        delete overlaySeriesRef.current[key];
      }
    }
    for (const [key, cfg] of Object.entries(desired)) {
      if (!overlaySeriesRef.current[key]) {
        overlaySeriesRef.current[key] = chart.addSeries(
          LineSeries,
          { color: cfg.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false },
          0,
        );
      }
      overlaySeriesRef.current[key].setData(
        cfg.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })),
      );
    }
  }, [indicators.sma, indicators.smaPeriod, indicators.ema, indicators.emaPeriod, indicators.vwap, history.data]);

  // 5) RSI pane (index 1).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!indicators.rsi) {
      if (rsiSeriesRef.current) {
        chart.removeSeries(rsiSeriesRef.current);
        rsiSeriesRef.current = null;
      }
      return;
    }
    if (!rsiSeriesRef.current) {
      rsiSeriesRef.current = chart.addSeries(
        LineSeries, { color: "#8b5cf6", lineWidth: 2, priceLineVisible: false }, 1,
      );
    }
    const points = rsi(candlesRef.current, 14);
    rsiSeriesRef.current.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
  }, [indicators.rsi, history.data]);

  // 6) MACD pane (index 1, or 2 if RSI is also showing).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!indicators.macd) {
      if (macdSeriesRef.current) {
        chart.removeSeries(macdSeriesRef.current.macd);
        chart.removeSeries(macdSeriesRef.current.signal);
        chart.removeSeries(macdSeriesRef.current.hist);
        macdSeriesRef.current = null;
      }
      return;
    }
    const paneIndex = indicators.rsi ? 2 : 1;
    if (!macdSeriesRef.current) {
      macdSeriesRef.current = {
        macd: chart.addSeries(LineSeries, { color: "#38bdf8", lineWidth: 2, priceLineVisible: false }, paneIndex),
        signal: chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2, priceLineVisible: false }, paneIndex),
        hist: chart.addSeries(HistogramSeries, { priceLineVisible: false }, paneIndex),
      };
    }
    const result = macd(candlesRef.current);
    macdSeriesRef.current.macd.setData(result.macd.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    macdSeriesRef.current.signal.setData(result.signal.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    macdSeriesRef.current.hist.setData(
      result.histogram.map((p) => ({
        time: p.time as UTCTimestamp, value: p.value, color: p.value >= 0 ? `${BULL}66` : `${BEAR}66`,
      })),
    );
  }, [indicators.macd, indicators.rsi, history.data]);

  // 7) Trade markers (entry/exit) + SL/target/entry price lines for
  //    whichever trade is highlighted (clicked in the bottom tabs).
  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries || !markersRef.current) return;

    for (const line of priceLinesRef.current) candleSeries.removePriceLine(line);
    priceLinesRef.current = [];

    const markers: SeriesMarker<Time>[] = [];
    for (const t of trades) {
      if (t.entry_time && t.entry_price !== null) {
        markers.push({
          time: toTime(t.entry_time),
          position: t.action === "BUY" ? "belowBar" : "aboveBar",
          shape: t.action === "BUY" ? "arrowUp" : "arrowDown",
          color: BULL,
          text: `${t.action} @ ${t.entry_price}`,
        });
      }
      if (t.exit_time && t.exit_price !== null) {
        markers.push({
          time: toTime(t.exit_time),
          position: t.action === "BUY" ? "aboveBar" : "belowBar",
          shape: "circle",
          color: (t.pnl ?? 0) >= 0 ? BULL : BEAR,
          text: `${t.exit_reason ?? "EXIT"} @ ${t.exit_price}`,
        });
      }
      if (highlightedTradeId === t.id && t.status !== "CLOSED") {
        priceLinesRef.current.push(
          candleSeries.createPriceLine({
            price: t.stoploss, color: BEAR, lineWidth: 1, lineStyle: LineStyle.Dashed,
            title: "SL", axisLabelVisible: true,
          }),
        );
        t.targets.forEach((target, i) => {
          priceLinesRef.current.push(
            candleSeries.createPriceLine({
              price: target, color: BULL, lineWidth: 1, lineStyle: LineStyle.Dashed,
              title: t.targets.length > 1 ? `T${i + 1}` : "Target", axisLabelVisible: true,
            }),
          );
        });
        priceLinesRef.current.push(
          candleSeries.createPriceLine({
            price: t.entry_price ?? t.entry_trigger, color: AXIS_TEXT, lineWidth: 1,
            lineStyle: LineStyle.Dotted, title: "Entry", axisLabelVisible: true,
          }),
        );
      }
    }
    markersRef.current.setMarkers(markers);
  }, [trades, highlightedTradeId]);

  return (
    <div className="relative flex h-full min-h-0 flex-1 flex-col">
      {!selected && (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          Search or select an instrument to view its chart.
        </div>
      )}
      {selected && history.isLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 text-sm text-muted-foreground">
          Loading candles…
        </div>
      )}
      {selected && !history.isLoading && history.data && !history.data.available && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/80 px-6 text-center text-sm text-muted-foreground">
          No chart data available for this instrument{history.data.reason ? ` — ${history.data.reason}` : ""}.
        </div>
      )}
      {selected && history.data?.source === "ticks" && (
        <div className="absolute left-2 top-2 z-10 rounded bg-chart-3/20 px-2 py-0.5 text-[11px] font-medium text-chart-3">
          Derived from recorded ticks — broker candles unavailable
        </div>
      )}
      {selected && history.data?.partial_last && (
        <div className="absolute right-2 top-2 z-10 rounded bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">
          Last candle still forming
        </div>
      )}
      <div ref={containerRef} className={selected ? "h-full w-full" : "hidden"} />
    </div>
  );
}
