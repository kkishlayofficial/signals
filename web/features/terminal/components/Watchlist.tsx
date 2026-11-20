"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { InstrumentSearch } from "./InstrumentSearch";
import { PriceCell } from "./PriceCell";
import { useTerminalStore } from "@/stores/terminal";
import { usePositions } from "@/hooks/usePositions";
import { useQuote } from "../hooks/useQuote";
import { useInstrumentSubscription } from "../hooks/useInstrumentSubscription";
import { cn } from "@/lib/utils";
import { formatPercent } from "@/lib/format";
import type { Instrument } from "@/lib/api";

const STORAGE_KEY = "terminal.watchlist.v1";

type WatchedInstrument = { exchange: string; token: string; symbol: string; name: string | null };

function loadWatchlist(): WatchedInstrument[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return []; // private mode, cleared storage, or corrupt JSON -- never crash the page over this
  }
}

function saveWatchlist(items: WatchedInstrument[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {
    // best-effort convenience only; losing it is not a correctness issue
  }
}

function WatchRow({
  exchange, token, symbol, name, removable, onRemove,
}: WatchedInstrument & { removable?: boolean; onRemove?: () => void }) {
  const selected = useTerminalStore((s) => s.selected);
  const selectInstrument = useTerminalStore((s) => s.selectInstrument);
  const { data: quote } = useQuote(exchange, token);
  useInstrumentSubscription(exchange, token, "1m"); // live price for as long as this row is rendered
  const isSelected = selected?.exchange === exchange && selected?.token === token;

  return (
    <div
      className={cn(
        "group flex cursor-pointer items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent/50",
        isSelected && "bg-accent",
      )}
      onClick={() => selectInstrument({ exchange, token, symbol, name })}
    >
      <div className="flex min-w-0 flex-col">
        <span className="truncate font-medium">{symbol}</span>
        <span className="text-[11px] text-muted-foreground">{exchange}</span>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex flex-col items-end">
          <PriceCell token={token} fallback={quote?.ltp} />
          <span
            className={cn(
              "text-[11px] tabular",
              (quote?.pct_change ?? 0) > 0 && "text-bull",
              (quote?.pct_change ?? 0) < 0 && "text-bear",
              !quote?.pct_change && "text-muted-foreground",
            )}
          >
            {formatPercent(quote?.pct_change, 2)}
          </span>
        </div>
        {removable && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onRemove?.();
            }}
            className="invisible cursor-pointer text-muted-foreground hover:text-bear group-hover:visible"
            aria-label={`Remove ${symbol} from watchlist`}
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}

export function Watchlist() {
  const [watched, setWatched] = useState<WatchedInstrument[]>([]);
  const { data: positions } = usePositions();

  useEffect(() => {
    // Deliberately re-read after mount, not in the initializer: this page
    // is server-rendered too (confirmed by `next build`'s static-shell
    // output for /terminal), where localStorage doesn't exist --
    // loadWatchlist()'s try/catch returns [] there. A useState lazy
    // initializer would freeze on that [] through hydration; only a
    // post-mount effect re-reads the real client-side value.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setWatched(loadWatchlist());
  }, []);

  function addInstrument(inst: Instrument) {
    setWatched((prev) => {
      if (prev.some((w) => w.exchange === inst.exchange && w.token === inst.token)) return prev;
      const next = [...prev, { exchange: inst.exchange, token: inst.token, symbol: inst.symbol, name: inst.name }];
      saveWatchlist(next);
      return next;
    });
  }

  function removeInstrument(exchange: string, token: string) {
    setWatched((prev) => {
      const next = prev.filter((w) => !(w.exchange === exchange && w.token === token));
      saveWatchlist(next);
      return next;
    });
  }

  const positionInstruments = (positions ?? [])
    .filter((p) => p.instrument_token)
    .map((p) => ({ id: p.id, exchange: p.exchange, token: p.instrument_token as string, symbol: p.tradingsymbol, name: p.symbol }));

  // Don't show a watchlist entry twice if it's already an open position.
  const watchedExcludingPositions = watched.filter(
    (w) => !positionInstruments.some((p) => p.exchange === w.exchange && p.token === w.token),
  );

  return (
    <div className="flex h-full flex-col gap-2 p-2">
      <InstrumentSearch onSelect={addInstrument} />

      <div className="flex-1 overflow-y-auto">
        {positionInstruments.length > 0 && (
          <div className="mb-2">
            <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Open Positions
            </div>
            {positionInstruments.map((p) => <WatchRow key={`pos-${p.id}`} {...p} />)}
          </div>
        )}

        <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Watchlist
        </div>
        {watchedExcludingPositions.length === 0 && (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            No instruments watched yet — search above to add one.
          </div>
        )}
        {watchedExcludingPositions.map((w) => (
          <WatchRow
            key={`watch-${w.exchange}-${w.token}`}
            {...w}
            removable
            onRemove={() => removeInstrument(w.exchange, w.token)}
          />
        ))}
      </div>
    </div>
  );
}
