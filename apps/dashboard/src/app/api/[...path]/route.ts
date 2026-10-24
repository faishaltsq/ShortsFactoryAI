import type { NextRequest } from "next/server";

type RouteContext = { params: Promise<{ path: string[] }> };

const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "range", "if-none-match", "if-modified-since"];
const HOP_BY_HOP_HEADERS = [
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
  "trailer", "transfer-encoding", "upgrade", "content-length",
];

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  let destination: URL;
  try {
    destination = new URL(process.env.STUDIO_API_ORIGIN ?? "http://127.0.0.1:8018");
    if (!new Set(["http:", "https:"]).has(destination.protocol) || destination.username || destination.password) {
      return Response.json({ detail: "invalid API origin" }, { status: 500 });
    }
    const { path } = await context.params;
    destination.pathname = `/api/${path.map(encodeURIComponent).join("/")}`;
    destination.search = request.nextUrl.search;
  } catch {
    return Response.json({ detail: "invalid API origin" }, { status: 500 });
  }

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const token = process.env.STUDIO_TOKEN;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  try {
    const body = request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();
    const upstream = await fetch(destination, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
    });
    const responseHeaders = new Headers(upstream.headers);
    for (const name of HOP_BY_HOP_HEADERS) responseHeaders.delete(name);
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json({ detail: "studio API unavailable" }, { status: 502 });
  }
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
