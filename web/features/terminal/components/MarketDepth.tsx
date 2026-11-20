"use client";

import { useTerminalStore } from "@/stores/terminal";
import { useDepth } from "../hooks/useDepth";
import { formatNumber } from "@/lib/format";

export function MarketDepth() {
  const selected = useTerminalStore((s) => s.selected);
  const { data: depth } = useDepth(selected?.exchange, selected?.token);

  if (!selected) return null;

  if (!depth?.available) {
    return (
      <div className="border-t p-3 text-center text-[11px] text-muted-foreground">
        Market depth unavailable{depth?.reason ? `: ${depth.reason}` : " for this instrument"}.
      </div>
    );
  }

  const maxQty = Math.max(
    1,
    ...depth.bid.map((l) => l.quantity ?? 0),
    ...depth.ask.map((l) => l.quantity ?? 0),
  );

  return (
    <div className="border-t p-2">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Market Depth
      </div>
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div className="flex flex-col gap-0.5">
          {depth.bid.slice(0, 5).map((level, i) => (
            <div key={i} className="relative flex items-center justify-between px-1 py-0.5 tabular">
              <div
                className="absolute inset-y-0 right-0 bg-bull-muted"
                style={{ width: `${((level.quantity ?? 0) / maxQty) * 100}%` }}
              />
              <span className="relative z-10 text-bull">{formatNumber(level.price)}</span>
              <span className="relative z-10 text-muted-foreground">{formatNumber(level.quantity, 0)}</span>
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-0.5">
          {depth.ask.slice(0, 5).map((level, i) => (
            <div key={i} className="relative flex items-center justify-between px-1 py-0.5 tabular">
              <div
                className="absolute inset-y-0 left-0 bg-bear-muted"
                style={{ width: `${((level.quantity ?? 0) / maxQty) * 100}%` }}
              />
              <span className="relative z-10 text-muted-foreground">{formatNumber(level.quantity, 0)}</span>
              <span className="relative z-10 text-bear">{formatNumber(level.price)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
