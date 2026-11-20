"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type TradeStatus } from "@/lib/api";

export type TradesFilter = {
  status?: TradeStatus;
  instrument?: string;
  profitable?: boolean;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
  sort?: string;
};

export function useTrades(filter: TradesFilter) {
  return useQuery({
    queryKey: ["trades", filter],
    queryFn: () => api.trades(filter),
    refetchInterval: 5_000,
  });
}
