/**
 * Server-side proxy to the FastAPI dashboard API.
 *
 * The browser never sees DASHBOARD_API_TOKEN -- it calls /api/proxy/<path>
 * on this Next.js server, which injects the real bearer token and forwards
 * to the backend. This route always runs per-request (no caching, no
 * prerendering): every byte here is live trading data.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.DASHBOARD_API_URL;
const BACKEND_TOKEN = process.env.DASHBOARD_API_TOKEN;

async function forward(req: NextRequest, path: string[]) {
  if (!BACKEND_URL || !BACKEND_TOKEN) {
    return NextResponse.json(
      { error: { code: "proxy_misconfigured", message: "DASHBOARD_API_URL/TOKEN not set" } },
      { status: 503 },
    );
  }

  const search = req.nextUrl.search;
  const target = `${BACKEND_URL}/api/${path.join("/")}${search}`;

  let body: string | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = await req.text();
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers: {
        Authorization: `Bearer ${BACKEND_TOKEN}`,
        "Content-Type": "application/json",
      },
      body,
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
    headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
  });
}

type RouteParams = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, { params }: RouteParams) {
  const { path } = await params;
  return forward(req, path);
}

export async function POST(req: NextRequest, { params }: RouteParams) {
  const { path } = await params;
  return forward(req, path);
}
