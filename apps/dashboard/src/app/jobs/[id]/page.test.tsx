import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

const getJob = vi.fn();
const getStudio = vi.fn();
const runJob = vi.fn();
const cancelJob = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "0123456789abcdef" }),
}));

vi.mock("next/link", () => ({
  default: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      getJob: (id: string) => getJob(id),
      getStudio: () => getStudio(),
      runJob: (id: string, payload: unknown) => runJob(id, payload),
      cancelJob: (id: string) => cancelJob(id),
    },
  };
});

import JobDetailPage from "@/app/jobs/[id]/page";

const JOB = {
  record: {
    id: "0123456789abcdef",
    title: "Cahaya matahari",
    state: "STORYBOARD_READY",
    attempts: 0,
    created_at: "2026-10-21T00:00:00+00:00",
    updated_at: "2026-10-21T00:01:00+00:00",
    last_error: null,
    payload: { provider_mode: "mock" },
  },
  events: [],
  artifacts: ["script.json"],
  run: { running: false },
};

const STUDIO = {
  saved: {
    version: 1,
    agents: {},
    budget: {},
    production: {},
    runner: { default_mode: "mock", default_stop: "storyboard" },
  },
  effective: { budget: {}, production: {} },
  agent_keys: [],
  default_prompts: {},
  runner_stops: ["research", "script", "creative", "storyboard", "audio", "render", "editorial", "approval"],
  personas: {},
  studio_path: "/tmp/studio.json",
  studio_exists: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  getJob.mockResolvedValue(JOB);
  getStudio.mockResolvedValue(STUDIO);
  runJob.mockResolvedValue({});
  cancelJob.mockResolvedValue({ ok: true, status: "idle" });
});

describe("job detail stop selector", () => {
  it("renders every stop the API reports, not a hardcoded subset", async () => {
    render(<JobDetailPage />);

    const select = await screen.findByLabelText("Berhenti di");
    await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(8));

    const values = Array.from(select.querySelectorAll("option")).map((option) => option.value);
    expect(values).toEqual(STUDIO.runner_stops);
    expect(values).toContain("editorial");
    expect(values).toContain("approval");
  });

  it("keeps storyboard selected by default and sends the chosen stop", async () => {
    render(<JobDetailPage />);

    const select = (await screen.findByLabelText("Berhenti di")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("storyboard"));

    fireEvent.change(select, { target: { value: "editorial" } });
    fireEvent.click(screen.getByRole("button", { name: /Jalankan/ }));

    await waitFor(() => expect(runJob).toHaveBeenCalledWith(JOB.record.id, { stop: "editorial" }));
  });

  it("falls back to storyboard while the studio payload is unavailable", async () => {
    getStudio.mockRejectedValue(new Error("offline"));
    render(<JobDetailPage />);

    const select = (await screen.findByLabelText("Berhenti di")) as HTMLSelectElement;
    await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(1));
    expect(select.value).toBe("storyboard");
  });
});
