"use client";

import { useRecentTrades } from "@/hooks/useRecentTrades";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatDateTime, formatNumber } from "@/lib/format";

type OrderRow = {
  key: string;
  orderId: string;
  symbol: string;
  side: string;
  kind: "ENTRY" | "EXIT";
  price: number | null;
  time: string | null;
};

export function OrdersTable() {
  const { data, isLoading } = useRecentTrades(undefined, 50);

  const rows: OrderRow[] = [];
  for (const t of data?.items ?? []) {
    if (t.broker_order_id) {
      rows.push({
        key: `${t.id}-entry`, orderId: t.broker_order_id, symbol: t.tradingsymbol,
        side: t.action, kind: "ENTRY", price: t.entry_price, time: t.entry_time,
      });
    }
    if (t.exit_order_id) {
      rows.push({
        key: `${t.id}-exit`, orderId: t.exit_order_id, symbol: t.tradingsymbol,
        side: t.action === "BUY" ? "SELL" : "BUY", kind: "EXIT", price: t.exit_price, time: t.exit_time,
      });
    }
  }
  rows.sort((a, b) => (b.time ?? "").localeCompare(a.time ?? ""));

  if (isLoading) {
    return <div className="p-4 text-center text-xs text-muted-foreground">Loading orders…</div>;
  }
  if (rows.length === 0) {
    return <div className="p-4 text-center text-xs text-muted-foreground">No orders yet.</div>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Order ID</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead>Type</TableHead>
          <TableHead className="text-right">Price</TableHead>
          <TableHead>Time</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.key}>
            <TableCell className="tabular text-xs text-muted-foreground">{r.orderId}</TableCell>
            <TableCell className="font-medium">{r.symbol}</TableCell>
            <TableCell>{r.side}</TableCell>
            <TableCell>
              <Badge variant="outline" className="text-[10px]">{r.kind}</Badge>
            </TableCell>
            <TableCell className="tabular text-right">{formatNumber(r.price)}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{formatDateTime(r.time)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
