"use client";

import { useState } from "react";
import { useTrades } from "@/hooks/useTrades";
import { TradesFilterBar, type TradesFilterState } from "@/features/trades/components/TradesFilterBar";
import { TradesTable } from "@/features/trades/components/TradesTable";
import { Pagination } from "@/components/pagination";

const PAGE_SIZE = 25;

const DEFAULT_FILTER: TradesFilterState = {
  status: "ALL",
  profitable: "ALL",
  instrument: "",
  dateFrom: "",
  dateTo: "",
  sort: "created_desc",
};

export default function TradesPage() {
  const [filter, setFilter] = useState<TradesFilterState>(DEFAULT_FILTER);
  const [page, setPage] = useState(1);

  const { data, isLoading, isError } = useTrades({
    status: filter.status === "ALL" ? undefined : filter.status,
    profitable: filter.profitable === "ALL" ? undefined : filter.profitable === "WIN",
    instrument: filter.instrument || undefined,
    date_from: filter.dateFrom || undefined,
    date_to: filter.dateTo || undefined,
    sort: filter.sort,
    page,
    page_size: PAGE_SIZE,
  });

  function handleFilterChange(next: TradesFilterState) {
    setFilter(next);
    setPage(1);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b px-3 py-2 text-sm font-semibold">Trade History</div>

      <TradesFilterBar filter={filter} onChange={handleFilterChange} />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && (
          <div className="p-6 text-center text-sm text-muted-foreground">Loading trades…</div>
        )}
        {isError && (
          <div className="p-6 text-center text-sm text-bear">Could not load trade history.</div>
        )}
        {data && <TradesTable trades={data.items} />}
      </div>

      {data && (
        <Pagination
          page={data.page}
          pageSize={data.page_size}
          total={data.total}
          onPageChange={setPage}
          itemLabel="trade"
        />
      )}
    </div>
  );
}
