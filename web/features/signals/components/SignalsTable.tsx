"use client";

import { useRouter } from "next/navigation";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Signal } from "@/lib/api";

const STATUS_CLASS: Record<string, string> = {
  EXECUTED: "border-bull/30 bg-bull-muted text-bull",
  CLOSED: "border-bull/30 bg-bull-muted text-bull",
  REJECTED: "border-bear/30 bg-bear-muted text-bear",
  INVALID: "border-bear/30 bg-bear-muted text-bear",
  DUPLICATE: "border-bear/30 bg-bear-muted text-bear",
  CANCELLED: "border-bear/30 bg-bear-muted text-bear",
};

function firstLine(text: string): string {
  return text.split("\n").find((l) => l.trim().length > 0) ?? text;
}

export function SignalsTable({ signals }: { signals: Signal[] }) {
  const router = useRouter();

  if (signals.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        No signals match these filters.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>#</TableHead>
          <TableHead>Received</TableHead>
          <TableHead>Channel</TableHead>
          <TableHead>Signal</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Reject Reason</TableHead>
          <TableHead>Trade</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {signals.map((s) => (
          <TableRow key={s.id} className="cursor-pointer" onClick={() => router.push(`/signals/${s.id}`)}>
            <TableCell className="tabular text-muted-foreground">{s.id}</TableCell>
            <TableCell className="tabular text-xs text-muted-foreground">{formatDateTime(s.received_at)}</TableCell>
            <TableCell className="max-w-40 truncate text-xs text-muted-foreground">{s.channel_name ?? "—"}</TableCell>
            <TableCell className="max-w-56 truncate text-xs">{firstLine(s.raw_text)}</TableCell>
            <TableCell>
              <Badge variant="outline" className={cn("text-[10px]", STATUS_CLASS[s.status])}>
                {s.status}
              </Badge>
            </TableCell>
            <TableCell className="max-w-48 truncate text-xs text-muted-foreground">{s.reject_reason ?? "—"}</TableCell>
            <TableCell className="tabular text-xs text-muted-foreground">{s.trade_id ? `#${s.trade_id}` : "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
