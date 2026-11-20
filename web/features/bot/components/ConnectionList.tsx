import { cn } from "@/lib/utils";
import type { BotStatus, ConnectionStatus } from "@/lib/api";

function ConnectionRow({ label, status }: { label: string; status: ConnectionStatus }) {
  return (
    <div className="flex items-center justify-between rounded-md border px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={cn("size-1.5 rounded-full", status.connected ? "bg-bull animate-pulse" : "bg-bear")} />
        <span className="text-sm font-medium">{label}</span>
      </div>
      <div className="flex items-center gap-2 text-xs">
        <span className={status.connected ? "text-bull" : "text-bear"}>
          {status.connected ? "Connected" : "Disconnected"}
        </span>
        {status.detail && <span className="text-muted-foreground">({status.detail})</span>}
      </div>
    </div>
  );
}

export function ConnectionList({ status }: { status: BotStatus }) {
  return (
    <div className="flex flex-col gap-2 p-3 pt-0">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Connections</div>
      <ConnectionRow label="Telegram" status={status.telegram} />
      <ConnectionRow label="Angel Broker" status={status.angel_broker} />
      <ConnectionRow label="Market Feed" status={status.market_feed} />
      {status.last_error && (
        <div className="mt-1 rounded-md border border-bear/30 bg-bear-muted px-3 py-2 text-xs text-bear">
          Last error: {status.last_error}
          {status.last_error_at && (
            <span className="ml-1 text-muted-foreground">
              ({new Date(status.last_error_at).toLocaleString("en-IN")})
            </span>
          )}
        </div>
      )}
    </div>
  );
}
