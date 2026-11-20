import { formatCurrency, formatPercent, formatSignedCurrency } from "@/lib/format";
import { StatTile } from "@/components/stat-tile";
import type { Overview } from "@/lib/api";

export function OverviewSummary({ overview }: { overview: Overview }) {
  return (
    <div className="flex flex-col gap-2 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Today</div>
      <div className="flex flex-wrap gap-2">
        <StatTile label="Trades" value={String(overview.today.total_trades)} />
        <StatTile label="Wins / Losses" value={`${overview.today.wins} / ${overview.today.losses}`} />
        <StatTile
          label="Realized P&L"
          value={formatSignedCurrency(overview.today.realized_pnl)}
          valueClassName={overview.today.realized_pnl > 0 ? "text-bull" : overview.today.realized_pnl < 0 ? "text-bear" : undefined}
        />
      </div>

      <div className="mt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">All Time</div>
      <div className="flex flex-wrap gap-2">
        <StatTile label="Trades" value={String(overview.all_time.total_trades)} />
        <StatTile label="Wins / Losses" value={`${overview.all_time.wins} / ${overview.all_time.losses}`} />
        <StatTile
          label="Win Rate"
          value={overview.win_rate !== null ? formatPercent(overview.win_rate * 100, 1) : "—"}
        />
        <StatTile
          label="Profit Factor"
          value={overview.profit_factor !== null ? overview.profit_factor.toFixed(2) : "—"}
        />
        <StatTile label="Gross Profit" value={formatCurrency(overview.gross_profit)} valueClassName="text-bull" />
        <StatTile label="Gross Loss" value={formatCurrency(overview.gross_loss)} valueClassName="text-bear" />
        <StatTile
          label="Net P&L"
          value={formatSignedCurrency(overview.net_pnl)}
          valueClassName={overview.net_pnl > 0 ? "text-bull" : overview.net_pnl < 0 ? "text-bear" : undefined}
        />
      </div>

      <div className="mt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Live</div>
      <div className="flex flex-wrap gap-2">
        <StatTile label="Active Positions" value={String(overview.active_positions)} />
        <StatTile label="Pending Signals" value={String(overview.pending_signals)} />
        <StatTile label="Capital Deployed" value={formatCurrency(overview.capital_deployed, true)} />
        <StatTile
          label="Unrealized P&L"
          value={formatSignedCurrency(overview.unrealized_pnl)}
          valueClassName={overview.unrealized_pnl > 0 ? "text-bull" : overview.unrealized_pnl < 0 ? "text-bear" : undefined}
        />
      </div>
    </div>
  );
}
