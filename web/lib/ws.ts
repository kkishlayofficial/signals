/**
 * WebSocket client for the live event stream.
 *
 * - Mints a single-use ticket (via the Next.js server route) before every
 *   connection attempt -- the long-lived token never appears in a URL.
 * - Tracks the highest `seq` seen and reconnects with `?since_seq=N` so a
 *   drop never silently loses an event; the ring buffer on the server
 *   replays anything missed.
 * - Exponential backoff reconnect, capped.
 * - Framework-agnostic pub/sub: callers subscribe by event name. The
 *   Zustand stores (not this module) decide what to do with each event.
 */
import { mintWsTicket } from "./api";

export type ServerEvent = {
  seq?: number;
  id?: string;
  event: string;
  timestamp?: string;
  data?: Record<string, unknown>;
};

type Listener = (evt: ServerEvent) => void;
type SubKey = string; // `${exchange}:${token}:${interval}`

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL ?? "ws://127.0.0.1:8000/ws";
const MAX_BACKOFF_MS = 15_000;

export type ConnectionState = "idle" | "connecting" | "open" | "closed" | "error";

export class TerminalSocket {
  private ws: WebSocket | null = null;
  private lastSeq = 0;
  private backoffMs = 500;
  private listeners = new Map<string, Set<Listener>>();
  private wildcardListeners = new Set<Listener>();
  private statusListeners = new Set<(s: ConnectionState) => void>();
  private activeSubs = new Set<SubKey>(); // re-sent on every (re)connect
  private closedByUser = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private connectPromise: Promise<void> | null = null;

  on(event: string, fn: Listener): () => void {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(fn);
    return () => this.listeners.get(event)?.delete(fn);
  }

  onAny(fn: Listener): () => void {
    this.wildcardListeners.add(fn);
    return () => this.wildcardListeners.delete(fn);
  }

  onStatus(fn: (s: ConnectionState) => void): () => void {
    this.statusListeners.add(fn);
    return () => this.statusListeners.delete(fn);
  }

  async connect(): Promise<void> {
    if (this.connectPromise) return this.connectPromise;
    this.closedByUser = false;
    this.connectPromise = this._connect().finally(() => {
      this.connectPromise = null;
    });
    return this.connectPromise;
  }

  private async _connect(): Promise<void> {
    this._setStatus("connecting");
    let ticket: string;
    try {
      ticket = await mintWsTicket();
    } catch (e) {
      this._setStatus("error");
      this._scheduleReconnect();
      throw e;
    }

    const url = `${WS_BASE}?ticket=${encodeURIComponent(ticket)}${
      this.lastSeq > 0 ? `&since_seq=${this.lastSeq}` : ""
    }`;

    return new Promise((resolve) => {
      const ws = new WebSocket(url);
      this.ws = ws;

      ws.onopen = () => {
        this.backoffMs = 500;
        this._setStatus("open");
        // Re-establish every subscription this client cares about -- the
        // server has no memory of a previous connection's subscriptions.
        for (const key of this.activeSubs) {
          const [exchange, token, interval] = key.split(":");
          this._send({ action: "subscribe", exchange, token, interval });
        }
        resolve();
      };

      ws.onmessage = (ev) => {
        let parsed: ServerEvent;
        try {
          parsed = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (typeof parsed.seq === "number") this.lastSeq = Math.max(this.lastSeq, parsed.seq);
        this.wildcardListeners.forEach((fn) => fn(parsed));
        this.listeners.get(parsed.event)?.forEach((fn) => fn(parsed));
      };

      ws.onclose = () => {
        this._setStatus("closed");
        if (!this.closedByUser) this._scheduleReconnect();
        resolve();
      };

      ws.onerror = () => {
        this._setStatus("error");
      };
    });
  }

  disconnect(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  subscribe(exchange: string, token: string, interval: string): void {
    const key: SubKey = `${exchange}:${token}:${interval}`;
    this.activeSubs.add(key);
    this._send({ action: "subscribe", exchange, token, interval });
  }

  unsubscribe(exchange: string, token: string, interval: string): void {
    const key: SubKey = `${exchange}:${token}:${interval}`;
    this.activeSubs.delete(key);
    this._send({ action: "unsubscribe", exchange, token, interval });
  }

  private _send(payload: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
    // If not open, the subscribe is already recorded in activeSubs and will
    // be re-sent on the next onopen -- nothing lost, just deferred.
  }

  private _scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.closedByUser) void this.connect();
    }, this.backoffMs);
    this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
  }

  private _setStatus(s: ConnectionState): void {
    this.statusListeners.forEach((fn) => fn(s));
  }
}

let singleton: TerminalSocket | null = null;

/** One socket per browser tab, created lazily on first use (client-only). */
export function getSocket(): TerminalSocket {
  if (typeof window === "undefined") {
    throw new Error("getSocket() called on the server");
  }
  singleton ??= new TerminalSocket();
  return singleton;
}
