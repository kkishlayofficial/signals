import { formatCurrency, formatPercent, formatSignedCurrency } from "@/lib/format";
import { StatTile } from "@/components/stat-tile";
import type { Analytics } from "@/lib/api";

export function AnalyticsSummary({ analytics }: { analytics: Analytics }) {
  return (
    <div className="flex flex-wrap gap-2 p-3">
      <StatTile
        label="Net P&L"
        value={formatSignedCurrency(analytics.net_pnl)}
        valueClassName={analytics.net_pnl > 0 ? "text-bull" : analytics.net_pnl < 0 ? "text-bear" : undefined}
      />
      <StatTile
        label="Win Rate"
        value={analytics.win_rate !== null ? formatPercent(analytics.win_rate * 100, 1) : "—"}
      />
      <StatTile
        label="Profit Factor"
        value={analytics.profit_factor !== null ? analytics.profit_factor.toFixed(2) : "—"}
      />
      <StatTile label="Trades" value={String(analytics.total_trades)} />
      <StatTile label="Wins / Losses" value={`${analytics.wins} / ${analytics.losses}`} />
      <StatTile label="Gross Profit" value={formatCurrency(analytics.gross_profit)} valueClassName="text-bull" />
      <StatTile label="Gross Loss" value={formatCurrency(analytics.gross_loss)} valueClassName="text-bear" />
      <StatTile label="Charges" value={formatCurrency(analytics.total_charges)} />
    </div>
  );
}
