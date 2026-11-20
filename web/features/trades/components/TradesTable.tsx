"use client";

import { useRouter } from "next/navigation";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatDateTime, formatNumber, formatSignedCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Trade } from "@/lib/api";

export function TradesTable({ trades }: { trades: Trade[] }) {
  const router = useRouter();

  if (trades.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        No trades match these filters.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>#</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Entry Time</TableHead>
          <TableHead className="text-right">Entry</TableHead>
          <TableHead className="text-right">Exit</TableHead>
          <TableHead>Reason</TableHead>
          <TableHead>Exit Time</TableHead>
          <TableHead className="text-right">Net P&amp;L</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {trades.map((t) => (
          <TableRow key={t.id} className="cursor-pointer" onClick={() => router.push(`/trades/${t.id}`)}>
            <TableCell className="tabular text-muted-foreground">{t.id}</TableCell>
            <TableCell className="font-medium">{t.tradingsymbol}</TableCell>
            <TableCell>
              <Badge
                variant="outline"
                className={cn(
                  "text-[10px]",
                  t.action === "BUY" ? "border-bull/30 bg-bull-muted text-bull" : "border-bear/30 bg-bear-muted text-bear",
                )}
              >
                {t.action}
              </Badge>
            </TableCell>
            <TableCell>
              <Badge variant="outline" className="text-[10px]">{t.status}</Badge>
            </TableCell>
            <TableCell className="tabular text-xs text-muted-foreground">
              {formatDateTime(t.entry_time ?? t.created_at)}
            </TableCell>
            <TableCell className="tabular text-right">{formatNumber(t.entry_price ?? t.entry_trigger)}</TableCell>
            <TableCell className="tabular text-right">{formatNumber(t.exit_price)}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{t.exit_reason ?? "—"}</TableCell>
            <TableCell className="tabular text-xs text-muted-foreground">{formatDateTime(t.exit_time)}</TableCell>
            <TableCell
              className={cn(
                "tabular text-right font-medium",
                (t.net_pnl ?? 0) > 0 && "text-bull",
                (t.net_pnl ?? 0) < 0 && "text-bear",
              )}
            >
              {t.net_pnl !== null ? formatSignedCurrency(t.net_pnl) : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
