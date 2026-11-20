import { formatDateTime, formatDuration } from "@/lib/format";
import { StatTile } from "@/components/stat-tile";
import type { BotStatus } from "@/lib/api";

export function BotStatusSummary({ status }: { status: BotStatus }) {
  return (
    <div className="flex flex-wrap gap-2 p-3">
      <StatTile
        label="Mode"
        value={status.mode.toUpperCase()}
        valueClassName={status.mode === "live" ? "text-bear" : "text-bull"}
      />
      <StatTile label="Uptime" value={formatDuration(status.uptime_seconds)} />
      <StatTile label="Started" value={formatDateTime(status.started_at)} />
      <StatTile label="Last Signal" value={formatDateTime(status.last_signal_at)} />
      <StatTile label="Last Trade" value={formatDateTime(status.last_trade_at)} />
      <StatTile label="Last Tick" value={formatDateTime(status.last_tick_at)} />
      <StatTile
        label="Broker Errors"
        value={String(status.broker_errors)}
        valueClassName={status.broker_errors > 0 ? "text-bear" : undefined}
      />
      <StatTile
        label="Telegram Errors"
        value={String(status.telegram_errors)}
        valueClassName={status.telegram_errors > 0 ? "text-bear" : undefined}
      />
    </div>
  );
}
