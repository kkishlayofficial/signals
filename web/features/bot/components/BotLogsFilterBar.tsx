"use client";

import { cn } from "@/lib/utils";
import type { BotLogLevel } from "@/lib/api";

const LEVEL_OPTIONS: { value: BotLogLevel | "ALL"; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "INFO", label: "Info" },
  { value: "WARNING", label: "Warning" },
  { value: "ERROR", label: "Error" },
  { value: "DEBUG", label: "Debug" },
];

export function BotLogsFilterBar({ level, onChange }: {
  level: BotLogLevel | "ALL";
  onChange: (next: BotLogLevel | "ALL") => void;
}) {
  return (
    <div className="flex items-center gap-2 border-b p-3">
      <div className="flex items-center gap-0.5 rounded-md border bg-card p-0.5">
        {LEVEL_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={cn(
              "cursor-pointer rounded-sm px-2 py-1 text-xs font-medium whitespace-nowrap transition-colors",
              level === opt.value
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
