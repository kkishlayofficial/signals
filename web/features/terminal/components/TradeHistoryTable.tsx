"use client";

import { useRecentTrades } from "@/hooks/useRecentTrades";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatDateTime, formatNumber, formatSignedCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";

export function TradeHistoryTable() {
  const { data, isLoading } = useRecentTrades("CLOSED", 50);

  if (isLoading) {
    return <div className="p-4 text-center text-xs text-muted-foreground">Loading trade history…</div>;
  }
  if (!data || data.items.length === 0) {
    return <div className="p-4 text-center text-xs text-muted-foreground">No closed trades yet.</div>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>#</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead className="text-right">Entry</TableHead>
          <TableHead className="text-right">Exit</TableHead>
          <TableHead>Reason</TableHead>
          <TableHead>Exit Time</TableHead>
          <TableHead className="text-right">Net P&amp;L</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.items.map((t) => (
          <TableRow key={t.id}>
            <TableCell className="tabular text-muted-foreground">{t.id}</TableCell>
            <TableCell className="font-medium">{t.tradingsymbol}</TableCell>
            <TableCell>{t.action}</TableCell>
            <TableCell className="tabular text-right">{formatNumber(t.entry_price)}</TableCell>
            <TableCell className="tabular text-right">{formatNumber(t.exit_price)}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{t.exit_reason ?? "—"}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{formatDateTime(t.exit_time)}</TableCell>
            <TableCell
              className={cn(
                "tabular text-right font-medium",
                (t.net_pnl ?? 0) >= 0 ? "text-bull" : "text-bear",
              )}
            >
              {formatSignedCurrency(t.net_pnl)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
