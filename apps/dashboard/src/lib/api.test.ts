import { describe, expect, it } from "vitest";
import { parseFieldErrors } from "./api";

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
