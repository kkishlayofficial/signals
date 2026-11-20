"use client";

import { useState } from "react";
import { useBotStatus } from "@/hooks/useBotStatus";
import { useBotLogs } from "@/hooks/useBotLogs";
import { BotControls } from "@/features/bot/components/BotControls";
import { BotStatusSummary } from "@/features/bot/components/BotStatusSummary";
import { ConnectionList } from "@/features/bot/components/ConnectionList";
import { BotLogsFilterBar } from "@/features/bot/components/BotLogsFilterBar";
import { BotLogsTable } from "@/features/bot/components/BotLogsTable";
import type { BotLogLevel } from "@/lib/api";

export default function BotMonitoringPage() {
  const [level, setLevel] = useState<BotLogLevel | "ALL">("ALL");

  const { data: status, isLoading: statusLoading, isError: statusError } = useBotStatus();
  const { data: logs, isLoading: logsLoading, isError: logsError } = useBotLogs({
    level: level === "ALL" ? undefined : level,
    limit: 100,
  });

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="border-b px-3 py-2 text-sm font-semibold">Bot Monitoring</div>

      {statusLoading && (
        <div className="p-6 text-center text-sm text-muted-foreground">Loading bot status…</div>
      )}
      {statusError && (
        <div className="p-6 text-center text-sm text-bear">Could not load bot status.</div>
      )}

      {status && (
        <>
          <BotControls status={status} />
          <BotStatusSummary status={status} />
          <ConnectionList status={status} />
        </>
      )}

      <div className="border-t px-3 py-2 text-sm font-semibold">Event Log</div>
      <BotLogsFilterBar level={level} onChange={setLevel} />

      {logsLoading && (
        <div className="p-6 text-center text-sm text-muted-foreground">Loading logs…</div>
      )}
      {logsError && (
        <div className="p-6 text-center text-sm text-bear">Could not load bot logs.</div>
      )}
      {logs && <BotLogsTable logs={logs} />}
    </div>
  );
}
