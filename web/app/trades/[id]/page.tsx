"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useTradeDetail } from "@/hooks/useTradeDetail";
import { TradeDetailView } from "@/features/trades/components/TradeDetailView";

export default function TradeDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { data, isLoading, isError } = useTradeDetail(id);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Link href="/trades" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" />
          Trade History
        </Link>
      </div>

      {isLoading && (
        <div className="p-6 text-center text-sm text-muted-foreground">Loading trade…</div>
      )}
      {isError && (
        <div className="p-6 text-center text-sm text-bear">Trade not found.</div>
      )}
      {data && <TradeDetailView detail={data} />}
    </div>
  );
}
