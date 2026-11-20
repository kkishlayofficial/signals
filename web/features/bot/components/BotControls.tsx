"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { BotStatus } from "@/lib/api";

export function BotControls({ status }: { status: BotStatus }) {
  const queryClient = useQueryClient();

  const pauseMutation = useMutation({
    mutationFn: () => api.pauseBot(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bot-status"] }),
  });
  const resumeMutation = useMutation({
    mutationFn: () => api.resumeBot(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bot-status"] }),
  });
  const actionPending = pauseMutation.isPending || resumeMutation.isPending;

  return (
    <div className="flex items-center gap-3 border-b bg-card/50 p-3">
      <div
        className={cn(
          "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold tracking-wide",
          status.paused
            ? "border-chart-3/40 bg-chart-3/10 text-chart-3"
            : "border-bull/30 bg-bull-muted text-bull",
        )}
      >
        <span className={cn("size-1.5 rounded-full", status.paused ? "bg-chart-3" : "bg-bull animate-pulse")} />
        {status.paused ? "SIGNAL INTAKE PAUSED" : "SIGNAL INTAKE RUNNING"}
      </div>

      {status.paused ? (
        <Button
          variant="outline"
          size="sm"
          disabled={actionPending}
          onClick={() => resumeMutation.mutate()}
        >
          {resumeMutation.isPending ? "Resuming…" : "Resume"}
        </Button>
      ) : (
        <Button
          variant="destructive"
          size="sm"
          disabled={actionPending}
          onClick={() => {
            if (window.confirm("Pause new signal intake? Open positions are not affected.")) {
              pauseMutation.mutate();
            }
          }}
        >
          {pauseMutation.isPending ? "Pausing…" : "Pause"}
        </Button>
      )}

      {(pauseMutation.isError || resumeMutation.isError) && (
        <div className="text-xs text-bear">
          {(pauseMutation.error as Error | undefined)?.message
            ?? (resumeMutation.error as Error | undefined)?.message}
        </div>
      )}

      <div className="ml-auto text-xs text-muted-foreground">
        Pausing only stops new signals from opening trades — already-open positions keep running.
      </div>
    </div>
  );
}
