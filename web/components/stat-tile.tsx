import { cn } from "@/lib/utils";

export function StatTile({ label, value, valueClassName }: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="flex min-w-32 flex-col gap-1 rounded-md border px-3 py-2">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className={cn("tabular text-lg font-semibold", valueClassName)}>{value}</span>
    </div>
  );
}
