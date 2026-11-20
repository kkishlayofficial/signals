"use client";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { TradeStatus } from "@/lib/api";

const STATUS_OPTIONS: { value: TradeStatus | "ALL"; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "PENDING", label: "Pending" },
  { value: "ACTIVE", label: "Active" },
  { value: "CLOSED", label: "Closed" },
  { value: "CANCELLED", label: "Cancelled" },
];

const PROFITABLE_OPTIONS: { value: "ALL" | "WIN" | "LOSS"; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "WIN", label: "Wins" },
  { value: "LOSS", label: "Losses" },
];

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "created_desc", label: "Newest" },
  { value: "created_asc", label: "Oldest" },
  { value: "pnl_desc", label: "P&L high→low" },
  { value: "pnl_asc", label: "P&L low→high" },
];

function Pills<T extends string>({ options, value, onChange }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border bg-card p-0.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "cursor-pointer rounded-sm px-2 py-1 text-xs font-medium whitespace-nowrap transition-colors",
            value === opt.value
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export type TradesFilterState = {
  status: TradeStatus | "ALL";
  profitable: "ALL" | "WIN" | "LOSS";
  instrument: string;
  dateFrom: string;
  dateTo: string;
  sort: string;
};

export function TradesFilterBar({ filter, onChange }: {
  filter: TradesFilterState;
  onChange: (next: TradesFilterState) => void;
}) {
  function set<K extends keyof TradesFilterState>(key: K, value: TradesFilterState[K]) {
    onChange({ ...filter, [key]: value });
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b p-3">
      <Pills options={STATUS_OPTIONS} value={filter.status} onChange={(v) => set("status", v)} />
      <Pills options={PROFITABLE_OPTIONS} value={filter.profitable} onChange={(v) => set("profitable", v)} />
      <Input
        placeholder="Search symbol…"
        value={filter.instrument}
        onChange={(e) => set("instrument", e.target.value)}
        className="w-40"
      />
      <Input
        type="date"
        value={filter.dateFrom}
        onChange={(e) => set("dateFrom", e.target.value)}
        className="w-36"
      />
      <span className="text-xs text-muted-foreground">to</span>
      <Input
        type="date"
        value={filter.dateTo}
        onChange={(e) => set("dateTo", e.target.value)}
        className="w-36"
      />
      <div className="ml-auto">
        <Pills options={SORT_OPTIONS} value={filter.sort} onChange={(v) => set("sort", v)} />
      </div>
    </div>
  );
}
