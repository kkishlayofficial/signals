"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useInstrumentSearch(query: string) {
  return useQuery({
    queryKey: ["instrument-search", query],
    queryFn: () => api.searchInstruments(query),
    enabled: query.trim().length > 0,
    staleTime: 60_000,
  });
}
