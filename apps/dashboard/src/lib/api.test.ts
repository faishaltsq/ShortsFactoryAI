import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, parseFieldErrors } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("parseFieldErrors", () => {
  it("memetakan 422 FastAPI ke loc+msg", () => {
    const detail = [
      { loc: ["body", "agents", "ScriptAgent", "temperature"], msg: "Input should be less than or equal to 2" },
    ];
    expect(parseFieldErrors(detail)).toEqual([
      { loc: ["body", "agents", "ScriptAgent", "temperature"], msg: "Input should be less than or equal to 2" },
    ]);
  });

  it("aman terhadap detail bukan array", () => {
    expect(parseFieldErrors("oops")).toEqual([]);
    expect(parseFieldErrors(undefined)).toEqual([]);
    expect(parseFieldErrors([{ msg: "tanpa loc" }])).toEqual([{ loc: [], msg: "tanpa loc" }]);
  });
});

describe("api error detail", () => {
  it("preserves field details from exactly one failed request", async () => {
    const detail = [
      { loc: ["body", "agents", "ScriptAgent", "temperature"], msg: "Must be at most 2" },
    ];
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ detail }), { status: 422 }));
    vi.stubGlobal("fetch", fetchMock);
    const error = await api
      .putStudio({
        version: 1,
        agents: {},
        budget: {},
        production: {},
        runner: { default_mode: "mock", default_stop: "storyboard" },
      })
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).detail).toEqual(detail);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
