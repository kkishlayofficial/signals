"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useSignalDetail(id: number) {
  return useQuery({
    queryKey: ["signal-detail", id],
    queryFn: () => api.signalDetail(id),
  });
}
