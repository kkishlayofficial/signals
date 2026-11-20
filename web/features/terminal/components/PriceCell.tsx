"use client";

import { useEffect, useRef, useState } from "react";
import { usePrice } from "@/stores/ticks";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Scoped to exactly one token's slot in the ticks store -- an update to any
 * other token never re-renders this cell. Falls back to `fallback` (e.g.
 * the last REST-polled LTP) until a live tick arrives.
 */
export function PriceCell({ token, fallback, decimals = 2 }: {
  token: string | null | undefined;
  fallback?: number | null;
  decimals?: number;
}) {
  const tick = usePrice(token ?? undefined);
  const value = tick?.ltp ?? fallback ?? null;

  const prevRef = useRef<number | null>(null);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);

  // Comparing against and updating the ref happens here, after render --
  // never read/written during render itself.
  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = value;
    if (value === null || prev === null || value === prev) return;
    setFlash(value > prev ? "up" : "down");
    const timer = setTimeout(() => setFlash(null), 400);
    return () => clearTimeout(timer);
  }, [value]);

  return (
    <span
      className={cn(
        "tabular transition-colors duration-300",
        flash === "up" && "text-bull",
        flash === "down" && "text-bear",
      )}
    >
      {formatNumber(value, decimals)}
    </span>
  );
}
