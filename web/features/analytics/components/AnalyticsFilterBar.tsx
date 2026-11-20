"use client";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const MODE_OPTIONS: { value: "ALL" | "paper" | "live"; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "paper", label: "Paper" },
  { value: "live", label: "Live" },
];

export type AnalyticsFilterState = {
  dateFrom: string;
  dateTo: string;
  mode: "ALL" | "paper" | "live";
  symbol: string; // "ALL" or an exact symbol
};

function Pills<T extends string>({ options, value, onChange }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-0.5 rounded-md border bg-card p-0.5">
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

export function AnalyticsFilterBar({ filter, onChange, symbols }: {
  filter: AnalyticsFilterState;
  onChange: (next: AnalyticsFilterState) => void;
  symbols: string[];
}) {
  function set<K extends keyof AnalyticsFilterState>(key: K, value: AnalyticsFilterState[K]) {
    onChange({ ...filter, [key]: value });
  }

  const symbolOptions = [{ value: "ALL" as const, label: "All" }, ...symbols.map((s) => ({ value: s, label: s }))];

  return (
    <div className="flex flex-wrap items-center gap-2 border-b p-3">
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
      <Pills options={MODE_OPTIONS} value={filter.mode} onChange={(v) => set("mode", v)} />
      <Pills options={symbolOptions} value={filter.symbol} onChange={(v) => set("symbol", v)} />
    </div>
  );
}
