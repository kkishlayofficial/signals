"use client";

import { useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { useInstrumentSearch } from "../hooks/useInstrumentSearch";
import { Input } from "@/components/ui/input";
import type { Instrument } from "@/lib/api";

export function InstrumentSearch({ onSelect }: { onSelect: (inst: Instrument) => void }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { data, isFetching } = useInstrumentSearch(query);

  function pick(inst: Instrument) {
    onSelect(inst);
    setQuery("");
    setOpen(false);
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search instruments…"
          className="h-8 pl-7 pr-7 text-sm"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 cursor-pointer text-muted-foreground hover:text-foreground"
            aria-label="Clear search"
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>

      {open && query && (
        <div className="absolute z-20 mt-1 w-full max-h-72 overflow-auto rounded-md border bg-popover shadow-lg">
          {isFetching && (
            <div className="px-3 py-2 text-xs text-muted-foreground">Searching…</div>
          )}
          {!isFetching && (data?.length ?? 0) === 0 && (
            <div className="px-3 py-2 text-xs text-muted-foreground">No instruments found.</div>
          )}
          {data?.map((inst) => (
            <button
              key={`${inst.exchange}:${inst.token}`}
              type="button"
              onClick={() => pick(inst)}
              className="flex w-full cursor-pointer flex-col items-start px-3 py-1.5 text-left hover:bg-accent"
            >
              <span className="text-sm font-medium tabular">{inst.symbol}</span>
              <span className="text-xs text-muted-foreground">
                {inst.exchange}
                {inst.expiry ? ` · ${inst.expiry}` : ""}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
