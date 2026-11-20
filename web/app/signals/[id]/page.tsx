"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useSignalDetail } from "@/hooks/useSignalDetail";
import { SignalDetailView } from "@/features/signals/components/SignalDetailView";

export default function SignalDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { data, isLoading, isError } = useSignalDetail(id);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Link href="/signals" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" />
          Signals
        </Link>
      </div>

      {isLoading && (
        <div className="p-6 text-center text-sm text-muted-foreground">Loading signal…</div>
      )}
      {isError && (
        <div className="p-6 text-center text-sm text-bear">Signal not found.</div>
      )}
      {data && <SignalDetailView signal={data} />}
    </div>
  );
}
