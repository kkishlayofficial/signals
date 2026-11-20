"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/** Polled every 2s -- matches MarketDataService's own quote cache TTL, so
 *  polling faster would just hammer the proxy for the same cached value. */
export function useQuote(exchange: string | undefined, token: string | undefined) {
  return useQuery({
    queryKey: ["quote", exchange, token],
    queryFn: () => api.quote(exchange!, token!),
    enabled: Boolean(exchange && token),
    refetchInterval: 2_000,
  });
}
