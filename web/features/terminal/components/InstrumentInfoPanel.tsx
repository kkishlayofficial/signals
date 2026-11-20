"use client";

import { useTerminalStore } from "@/stores/terminal";
import { useQuote } from "../hooks/useQuote";
import { PriceCell } from "./PriceCell";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular font-medium">{value}</span>
    </div>
  );
}

export function InstrumentInfoPanel() {
  const selected = useTerminalStore((s) => s.selected);
  const { data: quote, isLoading } = useQuote(selected?.exchange, selected?.token);

  if (!selected) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-xs text-muted-foreground">
        Select an instrument to see its details.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      <div>
        <div className="truncate text-sm font-semibold">{selected.symbol}</div>
        <div className="text-xs text-muted-foreground">{selected.exchange}</div>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular">
          <PriceCell token={selected.token} fallback={quote?.ltp} />
        </span>
        <span
          className={cn(
            "text-sm tabular",
            (quote?.pct_change ?? 0) > 0 && "text-bull",
            (quote?.pct_change ?? 0) < 0 && "text-bear",
          )}
        >
          {formatPercent(quote?.pct_change)}
        </span>
      </div>

      {quote?.stale && (
        <div className="rounded bg-chart-3/15 px-2 py-1 text-[11px] font-medium text-chart-3">
          No live tick recently — showing last known values.
        </div>
      )}
      {!isLoading && quote && !quote.available && (
        <div className="rounded bg-bear-muted px-2 py-1 text-[11px] font-medium text-bear">
          Market data unavailable{quote.reason ? `: ${quote.reason}` : ""}.
        </div>
      )}

      <div className="rounded-md border p-2">
        <Row label="Open" value={formatNumber(quote?.open)} />
        <Row label="High" value={formatNumber(quote?.high)} />
        <Row label="Low" value={formatNumber(quote?.low)} />
        <Row label="Prev. Close" value={formatNumber(quote?.prev_close)} />
        <Row label="Volume" value={quote?.volume != null ? formatNumber(quote.volume, 0) : "—"} />
        <Row label="VWAP" value={formatNumber(quote?.vwap)} />
      </div>
    </div>
  );
}
