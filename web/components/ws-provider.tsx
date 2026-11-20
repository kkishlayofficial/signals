"use client";

import { useWsConnection } from "@/hooks/useWsConnection";

/** Mounted once near the app root so the WS connection persists across navigation. */
export function WsProvider({ children }: { children: React.ReactNode }) {
  useWsConnection();
  return <>{children}</>;
}
