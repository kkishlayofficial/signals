"use client";

import { useBotStatus } from "@/hooks/useBotStatus";
import { cn } from "@/lib/utils";

/**
 * Permanent mode indicator. Red the instant `mode` is ever "live" -- this
 * app's only acceptable default is everyone always knowing which one they're
 * looking at, per the spec's "never imply a simulated execution is real."
 */
export function StatusBadge() {
  const { data, isError } = useBotStatus();

  if (isError) {
    return (
      <div className="flex items-center gap-1.5 rounded-md border border-bear/30 bg-bear-muted px-2 py-1 text-xs font-medium text-bear">
        <span className="size-1.5 rounded-full bg-bear" />
        BACKEND UNREACHABLE
      </div>
    );
  }

  const mode = data?.mode ?? "paper";
  const isLive = mode === "live";

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold tracking-wide",
        isLive
          ? "border-bear/40 bg-bear-muted text-bear"
          : "border-bull/30 bg-bull-muted text-bull",
      )}
    >
      <span className={cn("size-1.5 rounded-full", isLive ? "bg-bear" : "bg-bull")} />
      {isLive ? "LIVE TRADING" : "PAPER TRADING"}
    </div>
  );
}
