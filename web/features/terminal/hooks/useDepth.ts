"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useDepth(exchange: string | undefined, token: string | undefined) {
  return useQuery({
    queryKey: ["depth", exchange, token],
    queryFn: () => api.depth(exchange!, token!),
    enabled: Boolean(exchange && token),
    refetchInterval: 2_000,
  });
}
