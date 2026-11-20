"use client";

import { useConnectionStore } from "@/stores/connection";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const LABEL: Record<string, string> = {
  idle: "Not connected",
  connecting: "Connecting…",
  open: "Live",
  closed: "Reconnecting…",
  error: "Connection error",
};

export function ConnectionIndicator() {
  const status = useConnectionStore((s) => s.status);
  const dotClass =
    status === "open"
      ? "bg-bull animate-pulse"
      : status === "connecting"
        ? "bg-chart-3"
        : status === "idle"
          ? "bg-muted-foreground"
          : "bg-bear";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className={cn("size-1.5 rounded-full", dotClass)} />
          <span className="hidden sm:inline">{LABEL[status]}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent>{LABEL[status]} — live event stream</TooltipContent>
    </Tooltip>
  );
}
