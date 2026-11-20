"use client";

import { useTerminalStore } from "@/stores/terminal";
import { cn } from "@/lib/utils";
import type { Interval } from "@/lib/api";

const TIMEFRAMES: { value: Interval; label: string }[] = [
  { value: "1m", label: "1m" },
  { value: "3m", label: "3m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "30m", label: "30m" },
  { value: "1h", label: "1h" },
  { value: "1d", label: "1D" },
];

export function TimeframeBar() {
  const timeframe = useTerminalStore((s) => s.timeframe);
  const setTimeframe = useTerminalStore((s) => s.setTimeframe);

  return (
    <div className="flex items-center gap-0.5 rounded-md border bg-card p-0.5">
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf.value}
          type="button"
          onClick={() => setTimeframe(tf.value)}
          className={cn(
            "cursor-pointer rounded-sm px-2 py-1 text-xs font-medium tabular transition-colors",
            timeframe === tf.value
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
          )}
        >
          {tf.label}
        </button>
      ))}
    </div>
  );
}
