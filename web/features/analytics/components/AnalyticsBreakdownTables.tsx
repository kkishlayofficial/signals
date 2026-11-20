"use client";

import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatSignedCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Analytics } from "@/lib/api";

function pnlClass(value: number): string | undefined {
  if (value > 0) return "text-bull";
  if (value < 0) return "text-bear";
  return undefined;
}

export function AnalyticsBreakdownTables({ analytics }: { analytics: Analytics }) {
  return (
    <div className="flex flex-col gap-6 p-3 lg:flex-row">
      <div className="flex-1">
        <div className="mb-2 text-sm font-semibold">By Day</div>
        {analytics.by_day.length === 0 ? (
          <div className="p-4 text-center text-sm text-muted-foreground">No closed trades in range.</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Day</TableHead>
                <TableHead className="text-right">Trades</TableHead>
                <TableHead className="text-right">Net P&amp;L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {analytics.by_day.map((d) => (
                <TableRow key={d.day}>
                  <TableCell className="tabular">{d.day}</TableCell>
                  <TableCell className="tabular text-right">{d.trades}</TableCell>
                  <TableCell className={cn("tabular text-right font-medium", pnlClass(d.net_pnl))}>
                    {formatSignedCurrency(d.net_pnl)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <div className="flex-1">
        <div className="mb-2 text-sm font-semibold">By Symbol</div>
        {analytics.by_symbol.length === 0 ? (
          <div className="p-4 text-center text-sm text-muted-foreground">No closed trades in range.</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead className="text-right">Trades</TableHead>
                <TableHead className="text-right">Wins</TableHead>
                <TableHead className="text-right">Net P&amp;L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {analytics.by_symbol.map((s) => (
                <TableRow key={s.symbol}>
                  <TableCell className="font-medium">{s.symbol}</TableCell>
                  <TableCell className="tabular text-right">{s.trades}</TableCell>
                  <TableCell className="tabular text-right">{s.wins}</TableCell>
                  <TableCell className={cn("tabular text-right font-medium", pnlClass(s.net_pnl))}>
                    {formatSignedCurrency(s.net_pnl)}
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
