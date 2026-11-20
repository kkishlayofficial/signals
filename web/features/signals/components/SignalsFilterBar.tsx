"use client";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { SignalStatus } from "@/lib/api";

const STATUS_OPTIONS: { value: SignalStatus | "ALL"; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "RECEIVED", label: "Received" },
  { value: "PARSED", label: "Parsed" },
  { value: "VALIDATED", label: "Validated" },
  { value: "EXECUTED", label: "Executed" },
  { value: "CLOSED", label: "Closed" },
  { value: "REJECTED", label: "Rejected" },
  { value: "DUPLICATE", label: "Duplicate" },
  { value: "INVALID", label: "Invalid" },
  { value: "CANCELLED", label: "Cancelled" },
];

export type SignalsFilterState = {
  status: SignalStatus | "ALL";
  dateFrom: string;
  dateTo: string;
};

export function SignalsFilterBar({ filter, onChange }: {
  filter: SignalsFilterState;
  onChange: (next: SignalsFilterState) => void;
}) {
  function set<K extends keyof SignalsFilterState>(key: K, value: SignalsFilterState[K]) {
    onChange({ ...filter, [key]: value });
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b p-3">
      <div className="flex flex-wrap items-center gap-0.5 rounded-md border bg-card p-0.5">
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => set("status", opt.value)}
            className={cn(
              "cursor-pointer rounded-sm px-2 py-1 text-xs font-medium whitespace-nowrap transition-colors",
              filter.status === opt.value
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
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
    </div>
  );
}
