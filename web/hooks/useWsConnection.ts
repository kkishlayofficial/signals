"use client";

import { useEffect } from "react";
import { getSocket, type ServerEvent } from "@/lib/ws";
import { useConnectionStore } from "@/stores/connection";
import { recordPrice, recordCandleUpdate } from "@/stores/ticks";

type CandleUpdateData = {
  exchange: string;
  token: string | number;
  interval: string;
  ts: string;
  o: number;
  h: number;
  l: number;
  c: number;
  closed: boolean;
};

/**
 * Owns the single app-wide WS connection: connects once, wires CANDLE_UPDATE
 * into the ticks store.
 *
 * There's no separate instrument-scoped PRICE_UPDATE event on the wire --
 * trade_manager's own PRICE_UPDATE is keyed by trade_id, not by
 * exchange+token, so it can't drive a token-keyed watchlist price. Every
 * CANDLE_UPDATE already carries the latest trade price as its `c` (close),
 * though, so that's used as the live price source for both the watchlist
 * and position rows -- one event, two uses, no backend change needed.
 *
 * Per-instrument subscriptions (watchlist rows, the open chart) are each
 * owned by the component that needs them -- see useInstrumentSubscription.
 * The Watchlist renders every open position as a row, so positions always
 * get a live subscription for as long as the terminal page is open.
 */
export function useWsConnection() {
  const setStatus = useConnectionStore((s) => s.setStatus);

  useEffect(() => {
    const socket = getSocket();
    const offStatus = socket.onStatus(setStatus);
    const offCandle = socket.on("CANDLE_UPDATE", (evt: ServerEvent) => {
      const d = evt.data as unknown as CandleUpdateData | undefined;
      if (!d?.token) return;
      const token = String(d.token);
      recordCandleUpdate({
        exchange: d.exchange, token, interval: d.interval,
        ts: d.ts, o: d.o, h: d.h, l: d.l, c: d.c, closed: d.closed,
      });
      recordPrice(token, d.c);
    });

    void socket.connect();

    return () => {
      offStatus();
      offCandle();
      // The socket itself is a module-level singleton that outlives any one
      // component (including this effect re-running under HMR/StrictMode),
      // so it's deliberately not disconnected here.
    };
  }, [setStatus]);
}
