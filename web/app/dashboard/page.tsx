"use client";

import Link from "next/link";
import { useOverview } from "@/hooks/useOverview";
import { usePositions } from "@/hooks/usePositions";
import { useSignals } from "@/hooks/useSignals";
import { OverviewSummary } from "@/features/overview/components/OverviewSummary";
import { PositionsTable } from "@/features/positions/components/PositionsTable";
import { SignalsTable } from "@/features/signals/components/SignalsTable";
import { formatDateTime } from "@/lib/format";

export default function DashboardPage() {
  const { data: overview, isLoading: overviewLoading, isError: overviewError } = useOverview();
  const { data: positions, isLoading: positionsLoading } = usePositions();
  const { data: signalsPage, isLoading: signalsLoading } = useSignals({ page: 1, page_size: 5 });

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-sm font-semibold">Dashboard</span>
        {overview && (
          <span className="text-xs text-muted-foreground">As of {formatDateTime(overview.as_of)}</span>
        )}
      </div>

      {overviewLoading && (
        <div className="p-6 text-center text-sm text-muted-foreground">Loading overview…</div>
      )}
      {overviewError && (
        <div className="p-6 text-center text-sm text-bear">Could not load overview.</div>
      )}
      {overview && <OverviewSummary overview={overview} />}

      <div className="flex items-center justify-between border-t px-3 py-2">
        <span className="text-sm font-semibold">Open Positions</span>
        <Link href="/positions" className="text-xs text-muted-foreground hover:text-foreground">
          View all →
        </Link>
      </div>
      {positionsLoading && (
        <div className="p-6 text-center text-sm text-muted-foreground">Loading positions…</div>
      )}
      {positions && <PositionsTable positions={positions.slice(0, 5)} />}

      <div className="flex items-center justify-between border-t px-3 py-2">
        <span className="text-sm font-semibold">Recent Signals</span>
        <Link href="/signals" className="text-xs text-muted-foreground hover:text-foreground">
          View all →
        </Link>
      </div>
      {signalsLoading && (
        <div className="p-6 text-center text-sm text-muted-foreground">Loading signals…</div>
      )}
      {signalsPage && <SignalsTable signals={signalsPage.items} />}
    </div>
  );
}
