"use client";

import { useRecentTrades } from "@/hooks/useRecentTrades";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatDateTime, formatNumber, formatSignedCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";

type ExecutionRow = {
  key: string;
  symbol: string;
  side: string;
  kind: "ENTRY" | "EXIT";
  price: number | null;
  quantity: number;
  time: string | null;
  pnl: number | null; // only meaningful on the EXIT row
};

/**
 * A chronological fill tape (oldest first), distinct from the Orders tab's
 * order-management framing (order IDs, newest first) -- this is "what
 * actually happened and what it was worth," not "what was sent to the
 * broker and when."
 */
export function ExecutionsTable() {
  const { data, isLoading } = useRecentTrades(undefined, 100);

  const rows: ExecutionRow[] = [];
  for (const t of data?.items ?? []) {
    const qty = t.quantity * t.lot_size;
    if (t.entry_time && t.entry_price !== null) {
      rows.push({
        key: `${t.id}-entry`, symbol: t.tradingsymbol, side: t.action,
        kind: "ENTRY", price: t.entry_price, quantity: qty, time: t.entry_time, pnl: null,
      });
    }
    if (t.exit_time && t.exit_price !== null) {
      rows.push({
        key: `${t.id}-exit`, symbol: t.tradingsymbol, side: t.action === "BUY" ? "SELL" : "BUY",
        kind: "EXIT", price: t.exit_price, quantity: qty, time: t.exit_time, pnl: t.net_pnl,
      });
    }
  }
  rows.sort((a, b) => (a.time ?? "").localeCompare(b.time ?? ""));

  if (isLoading) {
    return <div className="p-4 text-center text-xs text-muted-foreground">Loading executions…</div>;
  }
  if (rows.length === 0) {
    return <div className="p-4 text-center text-xs text-muted-foreground">No executions yet.</div>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Time</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead>Type</TableHead>
          <TableHead className="text-right">Fill Price</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          <TableHead className="text-right">Realized P&amp;L</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.key}>
            <TableCell className="text-xs text-muted-foreground">{formatDateTime(r.time)}</TableCell>
            <TableCell className="font-medium">{r.symbol}</TableCell>
            <TableCell>{r.side}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{r.kind}</TableCell>
            <TableCell className="tabular text-right">{formatNumber(r.price)}</TableCell>
            <TableCell className="tabular text-right">{r.quantity}</TableCell>
            <TableCell className={cn("tabular text-right font-medium", r.pnl !== null && (r.pnl >= 0 ? "text-bull" : "text-bear"))}>
              {r.pnl !== null ? formatSignedCurrency(r.pnl) : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
