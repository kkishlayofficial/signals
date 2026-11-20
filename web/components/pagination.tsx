"use client";

import { Button } from "@/components/ui/button";

export function Pagination({ page, pageSize, total, onPageChange, itemLabel = "item" }: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  itemLabel?: string;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex items-center justify-between gap-2 border-t p-3 text-xs text-muted-foreground">
      <span>{total} {itemLabel}{total === 1 ? "" : "s"}</span>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="xs"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          Previous
        </Button>
        <span className="tabular">Page {page} of {totalPages}</span>
        <Button
          variant="outline"
          size="xs"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
