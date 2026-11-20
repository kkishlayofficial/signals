"use client";

import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  formatCurrency, formatDateTime, formatDuration, formatNumber, formatSignedCurrency,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { useTradeSource } from "@/hooks/useTradeSource";
import type { TradeDetail } from "@/lib/api";

function SourceMessage({ tradeId, fallbackRawSignal }: { tradeId: number; fallbackRawSignal: string }) {
  const { data, isLoading } = useTradeSource(tradeId);

  // The channel message is the authoritative "what did they actually post"
  // record (channel + timestamp included); trade.raw_signal is the fallback
  // for trades opened before that link existed, so cross-checking still
  // has something to show.
  const message = data?.message;
  const text = message?.message_text ?? fallbackRawSignal;

  return (
    <div>
      <div className="mb-2 text-sm font-semibold">Source Message</div>
      <div className="rounded-md border p-3">
        {!isLoading && message && (
          <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
            <span>{message.channel_name ?? "Unknown channel"}</span>
            <span>·</span>
            <span>{formatDateTime(message.received_at)}</span>
          </div>
        )}
        <pre className="whitespace-pre-wrap break-words font-mono text-xs text-foreground">
          {text}
        </pre>
      </div>
    </div>
  );
}

function Field({ label, value, valueClassName }: {
  label: string;
  value: React.ReactNode;
  valueClassName?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className={cn("tabular text-sm", valueClassName)}>{value}</span>
    </div>
  );
}

export function TradeDetailView({ detail }: { detail: TradeDetail }) {
  const { trade, exits } = detail;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">{trade.tradingsymbol}</h1>
        <Badge
          variant="outline"
          className={trade.action === "BUY" ? "border-bull/30 bg-bull-muted text-bull" : "border-bear/30 bg-bear-muted text-bear"}
        >
          {trade.action}
        </Badge>
        <Badge variant="outline">{trade.status}</Badge>
        <span className="text-xs text-muted-foreground">#{trade.id} · {trade.mode}</span>
      </div>

      <div className="grid grid-cols-2 gap-3 rounded-md border p-3 sm:grid-cols-4">
        <Field label="Created" value={formatDateTime(trade.created_at)} />
        <Field label="Entry Time" value={formatDateTime(trade.entry_time)} />
        <Field label="Entry Trigger" value={formatNumber(trade.entry_trigger)} />
        <Field label="Entry Price" value={formatNumber(trade.entry_price)} />
        <Field label="Quantity" value={String(trade.quantity * trade.lot_size)} />
        <Field label="Stoploss" value={formatNumber(trade.stoploss)} valueClassName="text-bear" />
        <Field label="Targets" value={trade.targets.map((t) => formatNumber(t)).join(" / ")} valueClassName="text-bull" />
        <Field label="Trailing SL" value={formatNumber(trade.trailing_sl)} />

        <Field label="Exit Time" value={formatDateTime(trade.exit_time)} />
        <Field label="Exit Price" value={formatNumber(trade.exit_price)} />
        <Field label="Exit Reason" value={trade.exit_reason ?? "—"} />
        <Field label="Duration" value={formatDuration(trade.duration_seconds)} />
        <Field
          label="Gross P&L"
          value={trade.pnl !== null ? formatSignedCurrency(trade.pnl) : "—"}
          valueClassName={(trade.pnl ?? 0) > 0 ? "text-bull" : (trade.pnl ?? 0) < 0 ? "text-bear" : undefined}
        />
        <Field label="Charges" value={formatCurrency(trade.charges)} />
        <Field
          label="Net P&L"
          value={trade.net_pnl !== null ? formatSignedCurrency(trade.net_pnl) : "—"}
          valueClassName={(trade.net_pnl ?? 0) > 0 ? "text-bull font-semibold" : (trade.net_pnl ?? 0) < 0 ? "text-bear font-semibold" : undefined}
        />
        <Field label="Signal" value={trade.signal_id ? `#${trade.signal_id}` : "—"} />
      </div>

      {trade.notes && (
        <div className="rounded-md border p-3 text-sm text-muted-foreground">{trade.notes}</div>
      )}

      <SourceMessage tradeId={trade.id} fallbackRawSignal={trade.raw_signal} />

      <div>
        <div className="mb-2 text-sm font-semibold">Exits</div>
        {exits.length === 0 ? (
          <div className="p-4 text-center text-sm text-muted-foreground">No exits recorded.</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead className="text-right">Exit Price</TableHead>
                <TableHead className="text-right">Quantity</TableHead>
                <TableHead>Time</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead className="text-right">P&amp;L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {exits.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="tabular text-muted-foreground">{e.id}</TableCell>
                  <TableCell className="tabular text-right">{formatNumber(e.exit_price)}</TableCell>
                  <TableCell className="tabular text-right">{e.quantity}</TableCell>
                  <TableCell className="tabular text-xs text-muted-foreground">{formatDateTime(e.exit_time)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{e.reason}</TableCell>
                  <TableCell
                    className={cn("tabular text-right font-medium", e.pnl > 0 ? "text-bull" : e.pnl < 0 ? "text-bear" : undefined)}
                  >
                    {formatSignedCurrency(e.pnl)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
