import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const { scheduleProjection } = vi.hoisted(() => ({ scheduleProjection: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, scheduleProjection } };
});

import SchedulePage from "@/app/schedule/page";

beforeEach(() => {
  vi.clearAllMocks();
  scheduleProjection.mockResolvedValue({
    generated_at: "2026-10-23T08:00:00+00:00",
    total: 2,
    counts: { "ON GOING": 1, RESEARCHING: 0, UPCOMING: 1, SELESAI: 0, GAGAL: 0, TERTAHAN: 0 },
    entries: [
      {
        job_id: "1111111111111111",
        title: "Cerita bintang",
        status: "ON GOING",
        state: "STORYBOARD_READY",
        stage_label: "Storyboard",
        next_action: "Menyiapkan aset",
        genre: "science",
        content_type: "factual",
        templates: ["illustrated_story"],
        scene_count: 4,
        duration_ms: 35000,
        verification: "verified",
        sources: 2,
        progress: 30,
        due_at: null,
        plan_id: null,
        slot_status: null,
        attempts: 1,
        source: "production",
        approval_required: false,
        created_at: "2026-10-23T07:00:00+00:00",
        updated_at: "2026-10-23T07:30:00+00:00",
      },
      {
        job_id: "2222222222222222",
        title: "Komet berikutnya",
        status: "UPCOMING",
        state: "IDEA_DISCOVERY",
        stage_label: "Riset ide",
        next_action: "Dijadwalkan 24 Oct 08:00",
        genre: null,
        content_type: null,
        templates: [],
        scene_count: 0,
        duration_ms: null,
        verification: "unverified",
        sources: 0,
        progress: 0,
        due_at: "2026-10-24T08:00:00+00:00",
        plan_id: "plan-1",
        slot_status: "queued",
        attempts: 0,
        source: "mock",
        approval_required: false,
        created_at: "2026-10-23T07:00:00+00:00",
        updated_at: "2026-10-23T07:00:00+00:00",
      },
    ],
  });
});

describe("SchedulePage", () => {
  it("renders the read-only projection and filters by status", async () => {
    render(<SchedulePage />);
    expect(await screen.findByText("Cerita bintang")).toBeTruthy();
    expect(screen.getByText("Komet berikutnya")).toBeTruthy();
    fireEvent.change(screen.getByRole("combobox", { name: "Filter status jadwal" }), {
      target: { value: "UPCOMING" },
    });
    expect(screen.queryByText("Cerita bintang")).toBeNull();
    expect(screen.getByText("Komet berikutnya")).toBeTruthy();
    expect(scheduleProjection).toHaveBeenCalledTimes(1);
  });
});
