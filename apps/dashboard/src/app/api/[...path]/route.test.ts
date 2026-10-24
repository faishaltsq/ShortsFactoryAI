import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";

const originalOrigin = process.env.STUDIO_API_ORIGIN;
const originalToken = process.env.STUDIO_TOKEN;

afterEach(() => {
  vi.unstubAllGlobals();
  if (originalOrigin === undefined) delete process.env.STUDIO_API_ORIGIN;
  else process.env.STUDIO_API_ORIGIN = originalOrigin;
  if (originalToken === undefined) delete process.env.STUDIO_TOKEN;
  else process.env.STUDIO_TOKEN = originalToken;
});

describe("dashboard API proxy", () => {
  it("adds the server-side token and forwards range requests without exposing it", async () => {
    process.env.STUDIO_API_ORIGIN = "http://127.0.0.1:8018";
    process.env.STUDIO_TOKEN = "local-test-token";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("video bytes", { status: 206, headers: { "Content-Range": "bytes 0-3/12" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest("http://localhost:3018/api/jobs/job-1/video?part=1", {
      headers: { Range: "bytes=0-3", Authorization: "Bearer browser-value" },
    });

    const response = await GET(request, { params: Promise.resolve({ path: ["jobs", "job-1", "video"] }) });
    const [url, init] = fetchMock.mock.calls[0];

    expect(String(url)).toBe("http://127.0.0.1:8018/api/jobs/job-1/video?part=1");
    expect(new Headers(init.headers).get("range")).toBe("bytes=0-3");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer local-test-token");
    expect(response.status).toBe(206);
    expect(response.headers.get("content-range")).toBe("bytes 0-3/12");
    expect(await response.text()).toBe("video bytes");
    expect(response.headers.get("authorization")).toBeNull();
  });

  it("returns a bounded gateway error when the API cannot be reached", async () => {
    process.env.STUDIO_API_ORIGIN = "http://127.0.0.1:8018";
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const request = new NextRequest("http://localhost:3018/api/health");

    const response = await GET(request, { params: Promise.resolve({ path: ["health"] }) });
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "studio API unavailable" });
  });
});
