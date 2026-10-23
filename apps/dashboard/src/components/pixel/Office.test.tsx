import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { Member } from "@/lib/team";
import { Office } from "./Office";

const members: Member[] = [
  {
    id: "ScriptAgent",
    persona: "Sora",
    role: "Penulis",
    description: "Naskah",
    tier: "worker",
    stage: "SCRIPT_GENERATED",
    accent: "#f4ce72",
    zone: "Ide & cerita",
    available: true,
    editable: true,
  },
  {
    id: "PublishAgent",
    persona: "Kira",
    role: "Penjaga rilis",
    description: "Belum tersedia",
    tier: "deterministic",
    stage: "PRIVATE_UPLOAD",
    accent: "#a9b2c5",
    zone: "Pemeriksaan & rilis",
    available: false,
    editable: false,
  },
];

it("lets the operator inspect even an unavailable member without activating it", () => {
  const select = vi.fn();
  render(
    <Office
      members={members}
      selectedId="ScriptAgent"
      onSelect={select}
      detail={null}
      stale={false}
    />,
  );
  const button = screen.getByRole("button", { name: /Kira/ });
  fireEvent.click(button);
  expect(select).toHaveBeenCalledWith("PublishAgent");
  expect(screen.getByText("Belum tersedia")).toBeTruthy();
  expect(screen.getByRole("button", { name: /Sora/ }).getAttribute("aria-pressed")).toBe("true");
});
