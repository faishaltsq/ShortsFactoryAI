import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api";

const { approveJob, rejectJob } = vi.hoisted(() => ({
  approveJob: vi.fn(),
  rejectJob: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, approveJob, rejectJob } };
});

import { ApprovalControls } from "./ApprovalControls";

beforeEach(() => {
  vi.clearAllMocks();
  approveJob.mockResolvedValue({ job_id: "abc123", state: "APPROVED", gate: {} });
  rejectJob.mockResolvedValue({ job_id: "abc123", state: "REJECTED", reason: "revisi" });
});

describe("ApprovalControls", () => {
  it("only appears at the operator approval gate", () => {
    const { rerender } = render(<ApprovalControls jobId="abc123" state="TECHNICAL_QC" onDecision={vi.fn()} />);
    expect(screen.queryByTestId("approval-controls")).toBeNull();
    rerender(<ApprovalControls jobId="abc123" state="READY_FOR_APPROVAL" onDecision={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Keputusan operator" })).toBeTruthy();
  });

  it("requires a rejection reason and persists the operator decision", async () => {
    const onDecision = vi.fn();
    render(<ApprovalControls jobId="abc123" state="READY_FOR_APPROVAL" onDecision={onDecision} />);
    const reject = screen.getByRole("button", { name: "Tolak job" }) as HTMLButtonElement;
    expect(reject.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Alasan penolakan"), { target: { value: "  revisi sumber  " } });
    fireEvent.click(reject);

    await waitFor(() => expect(rejectJob).toHaveBeenCalledWith("abc123", "local-operator", "revisi sumber"));
    expect(onDecision).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Job ditolak dan alasannya tercatat.")).toBeTruthy();
  });

  it("shows server gate failures without making the approval decision", async () => {
    approveJob.mockRejectedValue(new ApiError(409, "artifact verification missing"));
    render(<ApprovalControls jobId="abc123" state="READY_FOR_APPROVAL" onDecision={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Setujui job" }));

    expect((await screen.findByRole("alert")).textContent).toContain("artifact verification missing");
    expect(approveJob).toHaveBeenCalledWith("abc123", "local-operator");
  });
});
