"use client";

import { usePositions } from "@/hooks/usePositions";
import { PositionsSummary } from "@/features/positions/components/PositionsSummary";
import { PositionsTable } from "@/features/positions/components/PositionsTable";

export default function PositionsPage() {
  const { data: positions, isLoading, isError } = usePositions();

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="border-b px-3 py-2 text-sm font-semibold">Open Positions</div>

      {isLoading && (
        <div className="p-6 text-center text-sm text-muted-foreground">Loading positions…</div>
      )}
      {isError && (
        <div className="p-6 text-center text-sm text-bear">Could not load positions.</div>
      )}

      {positions && (
        <>
          <PositionsSummary positions={positions} />
          <PositionsTable positions={positions} />
        </>
      )}
    </div>
  );
}
