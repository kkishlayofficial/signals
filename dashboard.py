"""
Local dashboard server.

Reads trade data from the SQLite database and serves a real-time web
dashboard.  No broker login needed — the bot writes LTP updates to the
DB as it monitors positions, and this server just reads them.

The /api/stream endpoint is a Server-Sent Events (SSE) feed: the server
checks the database every ~500ms and pushes an event the instant any
trade or price changes.  The browser stays up to date without polling.

Usage:
    python dashboard.py              # Start on port 8050
    python dashboard.py --port 9000  # Custom port
"""
import argparse
import hashlib
import http.server
import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "trades.db")
DASHBOARD_HTML = BASE_DIR / "dashboard.html"


def _connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row):
    d = dict(row)
    if d.get("targets"):
        try:
            d["targets"] = json.loads(d["targets"])
        except Exception:
            pass
    return d


def get_trades():
    conn = _connect()
    rows = conn.execute("SELECT * FROM trades ORDER BY id DESC").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_summary():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _connect()

    today_row = conn.execute("""
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN status='CLOSED' AND pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
            COALESCE(SUM(CASE WHEN status='CLOSED' AND pnl < 0 THEN 1 ELSE 0 END), 0) AS losses,
            COALESCE(SUM(CASE WHEN status='CLOSED' THEN pnl ELSE 0 END), 0) AS realized_pnl,
            COALESCE(SUM(CASE WHEN status IN ('PENDING','ACTIVE') THEN 1 ELSE 0 END), 0) AS open_count
        FROM trades WHERE DATE(created_at) = ?
    """, (today,)).fetchone()

    all_row = conn.execute("""
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN status='CLOSED' AND pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
            COALESCE(SUM(CASE WHEN status='CLOSED' AND pnl < 0 THEN 1 ELSE 0 END), 0) AS losses,
            COALESCE(SUM(CASE WHEN status='CLOSED' THEN pnl ELSE 0 END), 0) AS realized_pnl,
            COALESCE(SUM(CASE WHEN status IN ('PENDING','ACTIVE') THEN 1 ELSE 0 END), 0) AS open_count
        FROM trades
    """).fetchone()

    conn.close()
    return {
        "today": dict(today_row) if today_row else {},
        "all_time": dict(all_row) if all_row else {},
        "as_of": datetime.now().isoformat(timespec="seconds"),
    }


def get_tick_history(trade_id):
    conn = _connect()
    rows = conn.execute(
        "SELECT ltp, ts FROM tick_history WHERE trade_id = ? ORDER BY id DESC LIMIT 500",
        (trade_id,),
    ).fetchall()
    conn.close()
    return [{"ltp": r["ltp"], "ts": r["ts"]} for r in reversed(rows)]


def get_messages(limit=50):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM channel_messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_activity(limit=100):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_snapshot():
    return {
        "trades": get_trades(),
        "summary": get_summary(),
        "messages": get_messages(),
        "activity": get_activity(),
    }


def _snapshot_hash(snap):
    raw = json.dumps(snap, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._serve_html()
        elif path == "/api/trades":
            self._json(get_trades())
        elif path == "/api/summary":
            self._json(get_summary())
        elif path == "/api/ticks":
            tid = int(qs.get("trade_id", [0])[0])
            self._json(get_tick_history(tid) if tid else [])
        elif path == "/api/messages":
            self._json(get_messages())
        elif path == "/api/activity":
            self._json(get_activity())
        elif path == "/api/stream":
            self._serve_sse()
        else:
            self.send_error(404)

    def _serve_html(self):
        try:
            body = DASHBOARD_HTML.read_bytes()
        except FileNotFoundError:
            self.send_error(500, "dashboard.html not found next to dashboard.py")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        last_hash = None
        try:
            while True:
                snap = get_snapshot()
                h = _snapshot_hash(snap)
                if h != last_hash:
                    last_hash = h
                    payload = json.dumps(snap, default=str)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, fmt, *args):
        pass


class ThreadedHTTPServer(http.server.HTTPServer):
    """Handle each request in a new thread so SSE doesn't block the server."""
    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread,
                             args=(request, client_address))
        t.daemon = True
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def main():
    p = argparse.ArgumentParser(description="Signal trading dashboard")
    p.add_argument("--port", type=int, default=8050,
                   help="Port to serve on (default 8050)")
    args = p.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        print("Run the bot at least once to create it, or run: python main.py --stats")
        return

    srv = ThreadedHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Dashboard → http://localhost:{args.port}")
    print(f"Reading   → {DB_PATH}")
    print("Ctrl+C to stop.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        srv.server_close()


if __name__ == "__main__":
    main()
