"use client";

import { Watchlist } from "@/features/terminal/components/Watchlist";
import { ChartPanel } from "@/features/terminal/components/ChartPanel";
import { TimeframeBar } from "@/features/terminal/components/TimeframeBar";
import { IndicatorMenu } from "@/features/terminal/components/IndicatorMenu";
import { InstrumentInfoPanel } from "@/features/terminal/components/InstrumentInfoPanel";
import { MarketDepth } from "@/features/terminal/components/MarketDepth";
import { BottomTabs } from "@/features/terminal/components/BottomTabs";
import { useTerminalStore } from "@/stores/terminal";

export default function TerminalPage() {
  const selected = useTerminalStore((s) => s.selected);

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1">
        {/* Left: watchlist */}
        <aside className="w-64 shrink-0 border-r">
          <Watchlist />
        </aside>

        {/* Center: chart */}
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
            <div className="min-w-0 truncate text-sm font-semibold">
              {selected ? selected.symbol : "No instrument selected"}
            </div>
            <div className="flex items-center gap-2">
              <TimeframeBar />
              <IndicatorMenu />
            </div>
          </div>
          <div className="min-h-0 flex-1">
            <ChartPanel />
          </div>
        </section>

        {/* Right: instrument info + depth */}
        <aside className="flex w-72 shrink-0 flex-col border-l">
          <div className="min-h-0 flex-1">
            <InstrumentInfoPanel />
          </div>
          <MarketDepth />
        </aside>
      </div>

      {/* Bottom: positions/orders/history/executions/events */}
      <div className="h-64 shrink-0 border-t">
        <BottomTabs />
      </div>
    </div>
  );
}
