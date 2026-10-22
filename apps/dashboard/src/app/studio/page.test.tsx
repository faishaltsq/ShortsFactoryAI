import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ApiError } from "@/lib/api";

const getStudio = vi.fn();
const putStudio = vi.fn();
const getModels = vi.fn();
const listHistory = vi.fn();
const rollback = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      getStudio: () => getStudio(),
      putStudio: (payload: unknown) => putStudio(payload),
      getModels: () => getModels(),
      listHistory: () => listHistory(),
      rollback: (name: string) => rollback(name),
      listJobs: vi.fn().mockResolvedValue({ jobs: [], states: [], running: {} }),
    },
  };
});

import StudioPage from "@/app/studio/page";

const SAVED = {
  version: 1,
  agents: {},
  budget: {},
  production: {},
  runner: { default_mode: "mock", default_stop: "storyboard" },
};

const EFFECTIVE = {
  budget: { max_daily_tokens: 400000, max_daily_cost_usd: 2, max_retries: 5 },
  production: { fps: 30, target_duration_s: 40, videos_per_day: 1, tts_voice: "id-ID-ArdiNeural", tts_rate: "+0%" },
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => ({ matches: false })),
  });
  getStudio.mockResolvedValue({
    saved: SAVED,
    effective: EFFECTIVE,
    agent_keys: ["ScriptAgent", "ResearchAgent"],
    default_prompts: { ScriptAgent: "PROMPT DEFAULT SCRIPT", ResearchAgent: "PROMPT DEFAULT RISET" },
    runner_stops: ["research", "script", "storyboard"],
    personas: {
      ScriptAgent: {
        persona: "Sang Penulis",
        role: "Naskah 30-45 detik",
        description: "Merangkai hook tajam.",
        stage: "SCRIPT_GENERATED",
        tier: "worker",
        accent: "#fbbf24",
      },
      ResearchAgent: {
        persona: "Sang Peneliti",
        role: "Riset & sumber",
        description: "Mengais ide dari web.",
        stage: "IDEA_DISCOVERY",
        tier: "worker",
        accent: "#38bdf8",
      },
    },
    studio_path: "/tmp/studio.json",
    studio_exists: true,
  });
  getModels.mockResolvedValue({ models: ["tig/deepseek-v4.1-flash"], source: "http://localhost", error: null });
  listHistory.mockResolvedValue([]);
  putStudio.mockImplementation(async (payload) => ({ saved: payload, effective: EFFECTIVE }));
});

describe("StudioPage", () => {
  it("menampilkan agent dan mematikan Simpan selama belum ada perubahan", async () => {
    render(<StudioPage />);
    expect(await screen.findByText("ScriptAgent")).toBeTruthy();
    const save = screen.getByRole("button", { name: "Simpan perubahan" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
  });

  it("menandai belum tersimpan dan mengaktifkan Simpan setelah input berubah", async () => {
    render(<StudioPage />);
    await screen.findByText("ScriptAgent");

    const temps = screen.getAllByPlaceholderText("0.7") as HTMLInputElement[];
    fireEvent.change(temps[0], { target: { value: "0.4" } });

    expect(await screen.findByText("Belum tersimpan")).toBeTruthy();
    const save = screen.getByRole("button", { name: "Simpan perubahan" }) as HTMLButtonElement;
    expect(save.disabled).toBe(false);
  });

  it("mengirim payload hasil edit ke API saat Simpan ditekan", async () => {
    render(<StudioPage />);
    await screen.findByText("ScriptAgent");
    fireEvent.change(screen.getAllByPlaceholderText("0.7")[0], { target: { value: "0.4" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan perubahan" }));

    await waitFor(() => expect(putStudio).toHaveBeenCalledTimes(1));
    const payload = putStudio.mock.calls[0][0] as { agents: Record<string, { temperature: number }> };
    expect(payload.agents.ScriptAgent.temperature).toBe(0.4);
  });

  it("preserves each agent draft across selections without a PUT", async () => {
    render(<StudioPage />);
    await screen.findByText("ScriptAgent");
    fireEvent.change(screen.getByPlaceholderText("0.7"), { target: { value: "0.4" } });
    fireEvent.click(screen.getByRole("button", { name: /Sang Peneliti ·/ }));
    fireEvent.change(screen.getByPlaceholderText("0.7"), { target: { value: "0.8" } });
    fireEvent.click(screen.getByRole("button", { name: /Sang Penulis ·/ }));
    expect((screen.getByPlaceholderText("0.7") as HTMLInputElement).value).toBe("0.4");
    expect(putStudio).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Simpan perubahan" }));
    await waitFor(() => expect(putStudio).toHaveBeenCalledTimes(1));
    expect(putStudio.mock.calls[0][0].agents).toMatchObject({
      ScriptAgent: { temperature: 0.4 },
      ResearchAgent: { temperature: 0.8 },
    });
  });

  it("uses one request for 422 and keeps the edited value", async () => {
    putStudio.mockRejectedValue(
      new ApiError(422, "Nilai ditolak", [
        { loc: ["body", "agents", "ScriptAgent", "temperature"], msg: "Terlalu tinggi" },
      ]),
    );
    render(<StudioPage />);
    await screen.findByText("ScriptAgent");
    fireEvent.change(screen.getByPlaceholderText("0.7"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan perubahan" }));
    expect(await screen.findByText("Terlalu tinggi")).toBeTruthy();
    expect(putStudio).toHaveBeenCalledTimes(1);
    expect((screen.getByPlaceholderText("0.7") as HTMLInputElement).value).toBe("3");
    expect(screen.getByText("Belum tersimpan")).toBeTruthy();
  });

  it("maps budget errors without dropping the section name", async () => {
    putStudio.mockRejectedValue(
      new ApiError(422, "Nilai ditolak", [
        { loc: ["body", "budget", "max_daily_tokens"], msg: "Budget tidak valid" },
      ]),
    );
    render(<StudioPage />);
    await screen.findByText("ScriptAgent");
    fireEvent.change(screen.getByLabelText(/Token harian/), { target: { value: "-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan perubahan" }));
    expect(await screen.findByText("Budget tidak valid")).toBeTruthy();
  });

  it("resets only the selected prompt", async () => {
    render(<StudioPage />);
    await screen.findByText("ScriptAgent");
    fireEvent.change(screen.getByRole("textbox", { name: "System prompt" }), { target: { value: "Custom" } });
    fireEvent.click(screen.getByRole("button", { name: "Kembalikan ke default" }));
    expect((screen.getByRole("textbox", { name: "System prompt" }) as HTMLTextAreaElement).value).toBe("");
    expect(putStudio).not.toHaveBeenCalled();
  });

  it("accepts rollback as the new clean baseline and updates effective values", async () => {
    listHistory.mockResolvedValue([{ name: "studio-fixture.json", mtime: 1, config: SAVED }]);
    const restored = { ...SAVED, production: { fps: 60 } };
    rollback.mockResolvedValue({
      restored,
      effective: { ...EFFECTIVE, production: { ...EFFECTIVE.production, fps: 60 } },
    });
    render(<StudioPage />);
    await screen.findByText("ScriptAgent");
    fireEvent.click(await screen.findByRole("button", { name: /^Kembalikan$/ }));
    await waitFor(() => expect((screen.getByLabelText(/^FPS/) as HTMLInputElement).value).toBe("60"));
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Simpan perubahan" }) as HTMLButtonElement).disabled).toBe(true),
    );
    expect(screen.queryByText("Belum tersimpan")).toBeNull();
    expect(rollback).toHaveBeenCalledWith("studio-fixture.json");
  });
});
