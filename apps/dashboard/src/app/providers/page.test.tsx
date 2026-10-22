import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const providers = vi.fn();
const providerModels = vi.fn();
const getStudio = vi.fn();
const putStudio = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      providers: () => providers(),
      providerModels: (t: string) => providerModels(t),
      getStudio: () => getStudio(),
      putStudio: (p: unknown) => putStudio(p),
    },
  };
});

import ProvidersPage from "@/app/providers/page";

const PAYLOAD = {
  health: [
    { ref: "worker:deepseek", healthy: true, model: "eg/elf/deepseek-v4.1-flash" },
    { ref: "strategist:strategist-http", healthy: true, model: "eg/elf/deepseek-v4.1-flash" },
  ],
  mode: {
    worker_base_url: "http://localhost:20128/v1",
    worker_configured: true,
    strategist_model: "eg/elf/deepseek-v4.1-flash",
  },
  editable: {
    worker: {
      enabled: null,
      base_url: null,
      model: null,
      temperature: null,
      effective_base_url: "http://localhost:20128/v1",
      effective_model: "eg/elf/deepseek-v4.1-flash",
      has_key: true,
      configured: true,
    },
    strategist_http: {
      enabled: null,
      base_url: null,
      model: null,
      temperature: null,
      effective_base_url: "http://localhost:20128/v1",
      effective_model: "eg/elf/glm-5.3-flash",
      has_key: true,
      configured: true,
    },
  },
};

const STUDIO = {
  saved: {
    version: 1,
    agents: {},
    budget: { unlimited: true },
    production: {},
    runner: { default_mode: "live", default_stop: "render" },
  },
  effective: { budget: {}, production: {} },
  agent_keys: [],
  default_prompts: {},
  runner_stops: [],
  personas: {},
  studio_path: "/x/studio.json",
  studio_exists: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  providers.mockResolvedValue(PAYLOAD);
  providerModels.mockResolvedValue({ models: ["eg/elf/deepseek-v4.1-flash"], source: "x", error: null });
  getStudio.mockResolvedValue(STUDIO);
  putStudio.mockResolvedValue({ saved: STUDIO.saved, effective: STUDIO.effective });
});

describe("halaman providers", () => {
  it("menampilkan setelan yang bisa diedit untuk kedua provider HTTP", async () => {
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByText("Worker (HTTP)")).toBeTruthy());
    expect(screen.getByText("Strategist (HTTP)")).toBeTruthy();
    // Jalur CLI sudah dihapus: tidak boleh muncul lagi sebagai kartu.
    expect(screen.queryByText("Strategist (CLI)")).toBeNull();
  });

  it("setiap provider punya base URL dan tombol muat model", async () => {
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByText("Strategist (HTTP)")).toBeTruthy());

    const baseUrlInputs = screen.getAllByPlaceholderText(/http/i);
    expect(baseUrlInputs).toHaveLength(2);

    expect(screen.getAllByRole("button", { name: "Muat model" })).toHaveLength(2);

    expect(screen.getAllByText("Base URL")).toHaveLength(2);
  });

  it("tidak pernah menampilkan nilai API key", async () => {
    const withKey = JSON.parse(JSON.stringify(PAYLOAD));
    withKey.editable.worker.has_key = true;
    providers.mockResolvedValue(withKey);
    const { container } = render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByText("Worker (HTTP)")).toBeTruthy());
    expect(container.textContent).not.toMatch(/sk-|Bearer|api_key/i);
  });

  it("menyimpan setelan tanpa menghapus bagian studio lain", async () => {
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByText("Worker (HTTP)")).toBeTruthy());

    const baseUrlInputs = screen.getAllByPlaceholderText(/http/i);
    fireEvent.change(baseUrlInputs[0], { target: { value: "https://api.example.com/v1" } });

    fireEvent.click(screen.getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(putStudio).toHaveBeenCalled());
    const sent = putStudio.mock.calls[0][0];
    expect(sent.providers.worker.base_url).toBe("https://api.example.com/v1");
    // Bagian studio lain harus ikut terbawa, bukan tertimpa.
    expect(sent.budget.unlimited).toBe(true);
    expect(sent.runner.default_mode).toBe("live");
  });

  it("menandai belum tersimpan setelah ada perubahan", async () => {
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByText("Worker (HTTP)")).toBeTruthy());
    expect(screen.queryByText("Belum tersimpan")).toBeNull();
    const inputs = screen.getAllByPlaceholderText(/http/i);
    fireEvent.change(inputs[0], { target: { value: "https://x.example.com/v1" } });
    await waitFor(() => expect(screen.getByText("Belum tersimpan")).toBeTruthy());
  });

  it("menampilkan pesan bila API lama tidak mendukung pengaturan", async () => {
    const { editable: _drop, ...legacy } = PAYLOAD;
    providers.mockResolvedValue(legacy);
    render(<ProvidersPage />);
    await waitFor(() =>
      expect(screen.getByText(/belum mendukung pengaturan provider/i)).toBeTruthy(),
    );
  });
});
