"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useTradeSource(id: number) {
  return useQuery({
    queryKey: ["trade-source", id],
    queryFn: () => api.tradeSource(id),
  });
}
