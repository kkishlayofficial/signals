/**
 * Mints a single-use WS ticket by calling the backend's own
 * /api/auth/ws-ticket with the real bearer token (server-side only). The
 * browser calls this route, gets back a short-lived ticket, and puts THAT
 * on the WS URL -- the long-lived token never reaches client-visible state.
 */
import { NextResponse } from "next/server";

const BACKEND_URL = process.env.DASHBOARD_API_URL;
const BACKEND_TOKEN = process.env.DASHBOARD_API_TOKEN;

export async function POST() {
  if (!BACKEND_URL || !BACKEND_TOKEN) {
    return NextResponse.json(
      { error: { code: "proxy_misconfigured", message: "DASHBOARD_API_URL/TOKEN not set" } },
      { status: 503 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}/api/auth/ws-ticket`, {
      method: "POST",
      headers: { Authorization: `Bearer ${BACKEND_TOKEN}` },
      cache: "no-store",
    });
  } catch (e) {
    return NextResponse.json(
      { error: { code: "backend_unreachable", message: String(e) } },
      { status: 503 },
    );
  }

  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
