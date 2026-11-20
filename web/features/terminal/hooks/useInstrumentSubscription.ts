"use client";

import { useEffect } from "react";
import { getSocket } from "@/lib/ws";

/**
 * Subscribes to live ticks/candles for (exchange, token, interval) for as
 * long as the calling component is mounted with those values -- a
 * watchlist row subscribes at a fixed "1m" purely for live price, the chart
 * subscribes at whatever timeframe is currently selected. Multiple callers
 * can hold the same (token, interval) simultaneously; MarketDataService
 * refcounts it server-side, so this component's unmount only releases this
 * component's own interest, never anyone else's.
 */
export function useInstrumentSubscription(
  exchange: string | undefined,
  token: string | undefined,
  interval: string,
) {
  useEffect(() => {
    if (!exchange || !token) return;
    const socket = getSocket();
    socket.subscribe(exchange, token, interval);
    return () => socket.unsubscribe(exchange, token, interval);
  }, [exchange, token, interval]);
}
