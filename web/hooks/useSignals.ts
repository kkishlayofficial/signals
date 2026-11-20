"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type SignalStatus } from "@/lib/api";

export type SignalsFilter = {
  status?: SignalStatus;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
};

export function useSignals(filter: SignalsFilter) {
  return useQuery({
    queryKey: ["signals", filter],
    queryFn: () => api.signals(filter),
    refetchInterval: 5_000,
  });
}
