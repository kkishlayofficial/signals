"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/** Open positions (PENDING + ACTIVE). Polled as the reliable baseline;
 *  CANDLE_UPDATE over WS layers live price/P&L on top where available. */
export function usePositions() {
  return useQuery({
    queryKey: ["positions"],
    queryFn: api.positions,
    refetchInterval: 3_000,
  });
}
