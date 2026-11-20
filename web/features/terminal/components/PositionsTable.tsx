"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { usePositions } from "@/hooks/usePositions";
import { usePrice } from "@/stores/ticks";
import { useTerminalStore } from "@/stores/terminal";
import paper_trading from "@/lib/paper-pnl";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDuration, formatNumber, formatSignedCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Trade } from "@/lib/api";

function PositionRow({ trade }: { trade: Trade }) {
  const queryClient = useQueryClient();
  const selectInstrument = useTerminalStore((s) => s.selectInstrument);
  const setHighlightedTrade = useTerminalStore((s) => s.setHighlightedTrade);
  const liveTick = usePrice(trade.instrument_token ?? undefined);
  const ltp = liveTick?.ltp ?? trade.current_ltp ?? trade.entry_price ?? trade.entry_trigger;

  const unrealized = trade.status === "ACTIVE" && trade.entry_price !== null
    ? paper_trading.calculatePnl(trade, ltp)
    : null;

  const closeMutation = useMutation({
    mutationFn: () => api.closePosition(trade.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["positions"] }),
  });
  const cancelMutation = useMutation({
    mutationFn: () => api.cancelPosition(trade.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["positions"] }),
  });
  const actionPending = closeMutation.isPending || cancelMutation.isPending;

  function open() {
    if (!trade.instrument_token) return;
    selectInstrument({
      exchange: trade.exchange, token: trade.instrument_token,
      symbol: trade.tradingsymbol, name: trade.symbol,
    });
    setHighlightedTrade(trade.id);
  }

  return (
    <TableRow className="cursor-pointer" onClick={open}>
      <TableCell className="font-medium">{trade.tradingsymbol}</TableCell>
      <TableCell>
        <Badge
          variant="outline"
          className={cn(
            "text-[10px]",
            trade.action === "BUY" ? "border-bull/30 bg-bull-muted text-bull" : "border-bear/30 bg-bear-muted text-bear",
          )}
        >
          {trade.action}
        </Badge>
      </TableCell>
      <TableCell>
        <Badge variant="outline" className="text-[10px]">{trade.status}</Badge>
      </TableCell>
      <TableCell className="tabular text-right">{formatNumber(trade.entry_price ?? trade.entry_trigger)}</TableCell>
      <TableCell className="tabular text-right">{formatNumber(ltp)}</TableCell>
      <TableCell className="tabular text-right">{trade.quantity * trade.lot_size}</TableCell>
      <TableCell className="tabular text-right text-bear">{formatNumber(trade.stoploss)}</TableCell>
      <TableCell className="tabular text-right text-bull">{formatNumber(trade.targets[0])}</TableCell>
      <TableCell
        className={cn(
          "tabular text-right font-medium",
          unrealized !== null && (unrealized >= 0 ? "text-bull" : "text-bear"),
        )}
      >
        {unrealized !== null ? formatSignedCurrency(unrealized) : "—"}
      </TableCell>
      <TableCell className="tabular text-right text-muted-foreground">
        {formatDuration(trade.duration_seconds)}
      </TableCell>
      <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
        {trade.status === "ACTIVE" && (
          <Button
            variant="destructive"
            size="xs"
            disabled={actionPending}
            onClick={() => {
              if (window.confirm(`Close ${trade.tradingsymbol} now at the current LTP?`)) {
                closeMutation.mutate();
              }
            }}
          >
            {closeMutation.isPending ? "Closing…" : "Close"}
          </Button>
        )}
        {trade.status === "PENDING" && (
          <Button
            variant="outline"
            size="xs"
            disabled={actionPending}
            onClick={() => {
              if (window.confirm(`Cancel the pending order for ${trade.tradingsymbol}?`)) {
                cancelMutation.mutate();
              }
            }}
          >
            {cancelMutation.isPending ? "Cancelling…" : "Cancel"}
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}

export function PositionsTable() {
  const { data: positions, isLoading } = usePositions();

  if (isLoading) {
    return <div className="p-4 text-center text-xs text-muted-foreground">Loading positions…</div>;
  }
  if (!positions || positions.length === 0) {
    return <div className="p-4 text-center text-xs text-muted-foreground">No open positions.</div>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Entry</TableHead>
          <TableHead className="text-right">LTP</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          <TableHead className="text-right">SL</TableHead>
          <TableHead className="text-right">Target</TableHead>
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
