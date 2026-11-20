"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useTradeDetail(id: number) {
  return useQuery({
    queryKey: ["trade-detail", id],
    queryFn: () => api.tradeDetail(id),
    refetchInterval: 5_000,
  });
}
