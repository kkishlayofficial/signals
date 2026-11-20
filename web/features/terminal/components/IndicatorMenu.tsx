"use client";

import { SlidersHorizontal } from "lucide-react";
import { useTerminalStore } from "@/stores/terminal";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function IndicatorMenu() {
  const indicators = useTerminalStore((s) => s.indicators);
  const toggle = useTerminalStore((s) => s.toggleIndicator);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5 cursor-pointer">
          <SlidersHorizontal className="size-3.5" />
          Indicators
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel className="text-xs">Overlays</DropdownMenuLabel>
        <DropdownMenuCheckboxItem checked={indicators.sma} onCheckedChange={() => toggle("sma")}>
          SMA ({indicators.smaPeriod})
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={indicators.ema} onCheckedChange={() => toggle("ema")}>
          EMA ({indicators.emaPeriod})
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={indicators.vwap} onCheckedChange={() => toggle("vwap")}>
          VWAP
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs">Panes</DropdownMenuLabel>
        <DropdownMenuCheckboxItem checked={indicators.rsi} onCheckedChange={() => toggle("rsi")}>
          RSI (14)
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={indicators.macd} onCheckedChange={() => toggle("macd")}>
          MACD (12,26,9)
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
