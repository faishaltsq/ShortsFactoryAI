import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import type { Member } from "@/lib/team";
import { useStudio } from "@/lib/useStudio";
import { AgentInspector } from "./AgentInspector";

const member: Member = {
  id: "RenderAgent",
  persona: "Rendi",
  role: "Teknisi render",
  description: "Video",
  stage: "RENDERING",
  tier: "deterministic",
  accent: "#89c9cf",
  editable: false,
  available: true,
  personality: "Tekun",
  motto: "Harus bisa diputar.",
};

afterEach(() => vi.restoreAllMocks());

function Harness({ editable = false }: { editable?: boolean }) {
  const studio = useStudio();
  return (
    <AgentInspector
      member={{ ...member, id: editable ? "ScriptAgent" : member.id, editable }}
      state={{ kind: "idle", label: "Siap membantu" }}
      studio={studio}
      models={[]}
      modelsError={null}
    />
  );
}

it("keeps deterministic roles inspectable but offers no model controls", async () => {
  vi.spyOn(api, "getStudio").mockRejectedValue(new Error("fixture: not needed"));
  render(<Harness />);
  expect(screen.getByRole("heading", { name: "Rendi" })).toBeTruthy();
  expect(screen.queryByRole("spinbutton")).toBeNull();
  expect(screen.getByText("Dikelola sistem; tidak memakai override model.")).toBeTruthy();
});

it("has a labeled prompt and retains numeric and blank temperature input", () => {
  vi.spyOn(api, "getStudio").mockRejectedValue(new Error("fixture: not needed"));
  render(<Harness editable />);
  const input = screen.getByLabelText(/Temperature/);
  fireEvent.change(input, { target: { value: "0.4" } });
  expect((input as HTMLInputElement).value).toBe("0.4");
  fireEvent.change(input, { target: { value: "" } });
  expect((input as HTMLInputElement).value).toBe("");
  expect(screen.getByRole("textbox", { name: "System prompt" })).toBeTruthy();
});
