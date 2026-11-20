"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type Interval } from "@/lib/api";

export function useHistory(exchange: string | undefined, token: string | undefined, interval: Interval) {
  return useQuery({
    queryKey: ["history", exchange, token, interval],
    queryFn: () => api.history(exchange!, token!, interval),
    enabled: Boolean(exchange && token),
    // Candles don't need to be refetched on every render -- the chart gets
    // its live tail from WS CANDLE_UPDATE, not from re-polling this.
    staleTime: 30_000,
  });
}
