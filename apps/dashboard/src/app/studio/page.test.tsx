import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const getStudio = vi.fn();
const putStudio = vi.fn();
const getModels = vi.fn();
const listHistory = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      getStudio: () => getStudio(),
      putStudio: (payload: unknown) => putStudio(payload),
      getModels: () => getModels(),
      listHistory: () => listHistory(),
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
  getStudio.mockResolvedValue({
    saved: SAVED,
    effective: EFFECTIVE,
    agent_keys: ["ScriptAgent", "ResearchAgent"],
    default_prompts: { ScriptAgent: "PROMPT DEFAULT SCRIPT", ResearchAgent: "PROMPT DEFAULT RISET" },
    runner_stops: ["research", "script", "storyboard"],
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
});
