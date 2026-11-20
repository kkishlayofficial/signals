"use client";

import { useState } from "react";
import { useSignals } from "@/hooks/useSignals";
import { SignalsFilterBar, type SignalsFilterState } from "@/features/signals/components/SignalsFilterBar";
import { SignalsTable } from "@/features/signals/components/SignalsTable";
import { Pagination } from "@/components/pagination";

const PAGE_SIZE = 25;

const DEFAULT_FILTER: SignalsFilterState = {
  status: "ALL",
  dateFrom: "",
  dateTo: "",
};

export default function SignalsPage() {
  const [filter, setFilter] = useState<SignalsFilterState>(DEFAULT_FILTER);
  const [page, setPage] = useState(1);

  const { data, isLoading, isError } = useSignals({
    status: filter.status === "ALL" ? undefined : filter.status,
    date_from: filter.dateFrom || undefined,
    date_to: filter.dateTo || undefined,
    page,
    page_size: PAGE_SIZE,
  });

  function handleFilterChange(next: SignalsFilterState) {
    setFilter(next);
    setPage(1);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b px-3 py-2 text-sm font-semibold">Signals</div>

      <SignalsFilterBar filter={filter} onChange={handleFilterChange} />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && (
          <div className="p-6 text-center text-sm text-muted-foreground">Loading signals…</div>
        )}
        {isError && (
          <div className="p-6 text-center text-sm text-bear">Could not load signals.</div>
        )}
        {data && <SignalsTable signals={data.items} />}
      </div>

      {data && (
        <Pagination
          page={data.page}
          pageSize={data.page_size}
          total={data.total}
          onPageChange={setPage}
          itemLabel="signal"
        />
      )}
    </div>
  );
}
