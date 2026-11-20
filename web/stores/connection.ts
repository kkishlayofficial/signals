/**
 * WS connection status. Low-frequency, UI-driven -- a plain reactive
 * Zustand store (not the batched vanilla pattern in stores/ticks.ts) is
 * fine here since this changes a handful of times per session, not per
 * tick.
 */
import { create } from "zustand";
import type { ConnectionState } from "@/lib/ws";

type ConnectionStore = {
  status: ConnectionState;
  setStatus: (s: ConnectionState) => void;
};

export const useConnectionStore = create<ConnectionStore>((set) => ({
  status: "idle",
  setStatus: (status) => set({ status }),
}));
