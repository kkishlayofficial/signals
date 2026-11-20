"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { BotLogLevel } from "@/lib/api";

export function useBotLogs(filter: { level?: BotLogLevel; limit?: number }) {
  return useQuery({
    queryKey: ["bot-logs", filter],
    queryFn: () => api.botLogs(filter),
    refetchInterval: 10_000,
  });
}
