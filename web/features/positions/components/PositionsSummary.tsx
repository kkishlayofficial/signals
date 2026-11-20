import { formatCurrency, formatSignedCurrency } from "@/lib/format";
import { StatTile } from "@/components/stat-tile";
import type { Trade } from "@/lib/api";

export function PositionsSummary({ positions }: { positions: Trade[] }) {
  const active = positions.filter((p) => p.status === "ACTIVE");
  const pending = positions.filter((p) => p.status === "PENDING");

  const deployed = active.reduce(
    (sum, t) => sum + (t.entry_price ?? 0) * t.quantity * t.lot_size,
    0,
  );
  const unrealized = active.reduce((sum, t) => sum + (t.unrealized_pnl ?? 0), 0);

  return (
    <div className="flex flex-wrap gap-2 p-3">
      <StatTile label="Active" value={String(active.length)} />
      <StatTile label="Pending" value={String(pending.length)} />
      <StatTile label="Capital Deployed" value={formatCurrency(deployed, true)} />
      <StatTile
        label="Unrealized P&L"
        value={formatSignedCurrency(unrealized)}
        valueClassName={unrealized > 0 ? "text-bull" : unrealized < 0 ? "text-bear" : undefined}
      />
    </div>
  );
}
