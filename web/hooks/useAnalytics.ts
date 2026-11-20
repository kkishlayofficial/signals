"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type AnalyticsFilter = {
  date_from?: string;
  date_to?: string;
  mode?: "paper" | "live";
  symbol?: string;
};

export function useAnalytics(filter: AnalyticsFilter) {
  return useQuery({
    queryKey: ["analytics", filter],
    queryFn: () => api.analytics(filter),
    refetchInterval: 10_000,
  });
}
