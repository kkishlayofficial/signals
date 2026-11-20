"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Signal } from "@/lib/api";

const STATUS_CLASS: Record<string, string> = {
  EXECUTED: "border-bull/30 bg-bull-muted text-bull",
  CLOSED: "border-bull/30 bg-bull-muted text-bull",
  REJECTED: "border-bear/30 bg-bear-muted text-bear",
  INVALID: "border-bear/30 bg-bear-muted text-bear",
  DUPLICATE: "border-bear/30 bg-bear-muted text-bear",
  CANCELLED: "border-bear/30 bg-bear-muted text-bear",
};

export function SignalDetailView({ signal }: { signal: Signal }) {
  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">Signal #{signal.id}</h1>
        <Badge variant="outline" className={cn(STATUS_CLASS[signal.status])}>{signal.status}</Badge>
        {signal.trade_id && (
          <Link href={`/trades/${signal.trade_id}`} className="text-xs text-primary hover:underline">
            View trade #{signal.trade_id}
          </Link>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 rounded-md border p-3 sm:grid-cols-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Channel</span>
          <span className="text-sm">{signal.channel_name ?? "—"}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Received</span>
          <span className="tabular text-sm">{formatDateTime(signal.received_at)}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Logged</span>
          <span className="tabular text-sm">{formatDateTime(signal.created_at)}</span>
        </div>
      </div>

      {signal.reject_reason && (
        <div className="rounded-md border border-bear/30 bg-bear-muted p-3 text-sm text-bear">
          {signal.reject_reason}
        </div>
      )}

      <div>
        <div className="mb-2 text-sm font-semibold">Raw message</div>
        <pre className="whitespace-pre-wrap rounded-md border bg-card p-3 text-sm">{signal.raw_text || "—"}</pre>
      </div>

      {signal.parsed_json && (
        <div>
          <div className="mb-2 text-sm font-semibold">Parsed</div>
          <pre className="overflow-x-auto rounded-md border bg-card p-3 text-xs">
            {JSON.stringify(signal.parsed_json, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
