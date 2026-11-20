"use client";

import { useState } from "react";
import { useAnalytics } from "@/hooks/useAnalytics";
import { AnalyticsFilterBar, type AnalyticsFilterState } from "@/features/analytics/components/AnalyticsFilterBar";
import { AnalyticsSummary } from "@/features/analytics/components/AnalyticsSummary";
import { AnalyticsBreakdownTables } from "@/features/analytics/components/AnalyticsBreakdownTables";

const DEFAULT_FILTER: AnalyticsFilterState = {
  dateFrom: "",
  dateTo: "",
  mode: "ALL",
  symbol: "ALL",
};

export default function AnalyticsPage() {
  const [filter, setFilter] = useState<AnalyticsFilterState>(DEFAULT_FILTER);

  const { data, isLoading, isError } = useAnalytics({
    date_from: filter.dateFrom || undefined,
    date_to: filter.dateTo || undefined,
    mode: filter.mode === "ALL" ? undefined : filter.mode,
    symbol: filter.symbol === "ALL" ? undefined : filter.symbol,
  });

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="border-b px-3 py-2 text-sm font-semibold">Analytics</div>

      <AnalyticsFilterBar filter={filter} onChange={setFilter} symbols={data?.symbols ?? []} />

      {isLoading && (
        <div className="p-6 text-center text-sm text-muted-foreground">Loading analytics…</div>
      )}
      {isError && (
        <div className="p-6 text-center text-sm text-bear">Could not load analytics.</div>
      )}

      {data && (
        <>
          <AnalyticsSummary analytics={data} />
          <AnalyticsBreakdownTables analytics={data} />
        </>
      )}
    </div>
  );
}
