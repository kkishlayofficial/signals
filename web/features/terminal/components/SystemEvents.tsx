"use client";

import { useState } from "react";
import { useBotLogs } from "@/hooks/useBotLogs";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { BotLogLevel } from "@/lib/api";

const LEVELS: (BotLogLevel | "ALL")[] = ["ALL", "INFO", "WARNING", "ERROR", "DEBUG"];

const LEVEL_CLASS: Record<BotLogLevel, string> = {
  INFO: "text-muted-foreground",
  WARNING: "text-chart-3",
  ERROR: "text-bear",
  DEBUG: "text-chart-5",
};

export function SystemEvents() {
  const [filter, setFilter] = useState<BotLogLevel | "ALL">("ALL");
  const { data, isLoading } = useBotLogs({ level: filter === "ALL" ? undefined : filter });

  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-1 border-b p-2">
        {LEVELS.map((l) => (
          <Button
            key={l}
            size="sm"
            variant={filter === l ? "secondary" : "ghost"}
            className="h-6 cursor-pointer px-2 text-[11px]"
            onClick={() => setFilter(l)}
          >
            {l}
          </Button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-2 font-mono text-xs">
        {isLoading && <div className="text-muted-foreground">Loading events…</div>}
        {!isLoading && (data?.length ?? 0) === 0 && (
          <div className="text-muted-foreground">No events recorded yet.</div>
        )}
        {data?.map((e) => (
          <div key={e.id} className="flex gap-2 py-0.5">
            <span className="shrink-0 text-muted-foreground">{formatTime(e.ts)}</span>
            <span className={cn("shrink-0 font-semibold", LEVEL_CLASS[e.level])}>{e.level}</span>
            <span className="whitespace-pre-wrap break-words">{e.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
