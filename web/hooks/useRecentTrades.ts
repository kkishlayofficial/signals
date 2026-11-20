"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type TradeStatus } from "@/lib/api";

export function useRecentTrades(status?: TradeStatus, pageSize = 50) {
  return useQuery({
    queryKey: ["recent-trades", status, pageSize],
    queryFn: () => api.trades({ status, page_size: pageSize, sort: "id_desc" }),
    refetchInterval: 5_000,
  });
}
