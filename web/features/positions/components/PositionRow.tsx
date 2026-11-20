"use client";

import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { usePrice } from "@/stores/ticks";
import { useInstrumentSubscription } from "@/features/terminal/hooks/useInstrumentSubscription";
import { useTerminalStore } from "@/stores/terminal";
import paper_trading from "@/lib/paper-pnl";
import { TableCell, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import {
  formatCurrency, formatDateTime, formatDuration, formatNumber, formatSignedCurrency,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Trade } from "@/lib/api";

export function PositionRow({ trade }: { trade: Trade }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const selectInstrument = useTerminalStore((s) => s.selectInstrument);
  const setHighlightedTrade = useTerminalStore((s) => s.setHighlightedTrade);

  const closeMutation = useMutation({
    mutationFn: () => api.closePosition(trade.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["positions"] }),
  });
  const cancelMutation = useMutation({
    mutationFn: () => api.cancelPosition(trade.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["positions"] }),
  });
  const actionPending = closeMutation.isPending || cancelMutation.isPending;

  useInstrumentSubscription(trade.exchange, trade.instrument_token ?? undefined, "1m");
  const liveTick = usePrice(trade.instrument_token ?? undefined);
  const ltp = liveTick?.ltp ?? trade.current_ltp ?? trade.entry_price ?? trade.entry_trigger;

  const unrealized = trade.status === "ACTIVE" && trade.entry_price !== null
    ? paper_trading.calculatePnl(trade, ltp)
    : null;
  const deployed = (trade.entry_price ?? trade.entry_trigger) * trade.quantity * trade.lot_size;

  function openInTerminal() {
    if (!trade.instrument_token) return;
    selectInstrument({
      exchange: trade.exchange, token: trade.instrument_token,
      symbol: trade.tradingsymbol, name: trade.symbol,
    });
    setHighlightedTrade(trade.id);
    router.push("/terminal");
  }

  return (
    <TableRow
      className={cn(trade.instrument_token && "cursor-pointer")}
      onClick={openInTerminal}
    >
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
      <TableCell className="text-muted-foreground">{trade.mode}</TableCell>
      <TableCell className="tabular text-muted-foreground">{formatDateTime(trade.entry_time ?? trade.created_at)}</TableCell>
      <TableCell className="tabular text-right">
        {trade.status === "PENDING" ? formatNumber(trade.entry_trigger) : formatNumber(trade.entry_price)}
      </TableCell>
      <TableCell className="tabular text-right">{formatNumber(ltp)}</TableCell>
      <TableCell className="tabular text-right">{trade.quantity * trade.lot_size}</TableCell>
      <TableCell className="tabular text-right text-bear">{formatNumber(trade.stoploss)}</TableCell>
      <TableCell className="tabular text-right text-bull">{formatNumber(trade.targets[0])}</TableCell>
      <TableCell className="tabular text-right text-muted-foreground">{formatCurrency(deployed)}</TableCell>
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
        {(closeMutation.isError || cancelMutation.isError) && (
          <div className="mt-1 text-[10px] text-bear">
            {(closeMutation.error as Error | undefined)?.message
              ?? (cancelMutation.error as Error | undefined)?.message}
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}
