import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { BotLogEntry } from "@/lib/api";

const LEVEL_CLASS: Record<BotLogEntry["level"], string> = {
  INFO: "border-muted-foreground/30 bg-muted text-muted-foreground",
  DEBUG: "border-muted-foreground/30 bg-muted text-muted-foreground",
  WARNING: "border-chart-3/40 bg-chart-3/10 text-chart-3",
  ERROR: "border-bear/30 bg-bear-muted text-bear",
};

export function BotLogsTable({ logs }: { logs: BotLogEntry[] }) {
  if (logs.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        No log events match this filter.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Time</TableHead>
          <TableHead>Level</TableHead>
          <TableHead>Category</TableHead>
          <TableHead>Message</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {logs.map((entry) => (
          <TableRow key={entry.id}>
            <TableCell className="tabular text-muted-foreground">{formatDateTime(entry.ts)}</TableCell>
            <TableCell>
              <Badge variant="outline" className={cn("text-[10px]", LEVEL_CLASS[entry.level])}>
                {entry.level}
              </Badge>
            </TableCell>
            <TableCell className="text-muted-foreground">{entry.category}</TableCell>
            <TableCell>{entry.message}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
