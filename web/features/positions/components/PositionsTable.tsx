"use client";

import {
  Table, TableBody, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PositionRow } from "./PositionRow";
import type { Trade } from "@/lib/api";

export function PositionsTable({ positions }: { positions: Trade[] }) {
  if (positions.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        No open positions.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Mode</TableHead>
          <TableHead>Entry Time</TableHead>
          <TableHead className="text-right">Entry</TableHead>
          <TableHead className="text-right">LTP</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          <TableHead className="text-right">SL</TableHead>
          <TableHead className="text-right">Target</TableHead>
          <TableHead className="text-right">Deployed</TableHead>
          <TableHead className="text-right">Unrealized P&amp;L</TableHead>
          <TableHead className="text-right">Duration</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((t) => <PositionRow key={t.id} trade={t} />)}
      </TableBody>
    </Table>
  );
}
