"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Trades (open or closed) against the selected instrument, for chart
 * markers (entry/exit) and SL/target price lines.
 *
 * There's no "trades by token" endpoint in the REST contract -- it filters
 * a generous recent page client-side instead, which is fine at this data
 * volume and avoids a bespoke endpoint for one chart feature.
 */
export function useTradesForInstrument(exchange: string | undefined, token: string | undefined) {
  const query = useQuery({
    queryKey: ["trades-recent-for-chart"],
    queryFn: () => api.trades({ page_size: 100, sort: "id_desc" }),
    staleTime: 10_000,
  });

  const matching = exchange && token
    ? (query.data?.items.filter((t) => t.exchange === exchange && t.instrument_token === token) ?? [])
    : [];

  return { ...query, trades: matching };
}
