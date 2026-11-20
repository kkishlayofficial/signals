"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Polled, not WS-driven: BOT_STATUS_UPDATE events land in Phase 5 alongside
 * pause/resume. A 10s poll is plenty for a status badge that isn't on the
 * trading-critical path.
 */
export function useBotStatus() {
  return useQuery({
    queryKey: ["bot-status"],
    queryFn: api.botStatus,
    refetchInterval: 10_000,
  });
}
