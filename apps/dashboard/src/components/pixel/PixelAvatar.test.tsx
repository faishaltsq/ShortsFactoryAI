import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { PixelAvatar } from "./PixelAvatar";
import type { Member } from "@/lib/team";
const member: Member = { id: "ScriptAgent", persona: "Sora", role: "Penulis", description: "Naskah",
  stage: "SCRIPT_GENERATED", tier: "worker", accent: "#f4ce72", accessory: "pencil", hair: "ponytail",
  skin: "warm", editable: true, available: true };
it("renders a crisp local character without hiding the parent's accessible identity", () => {
  const { container } = render(<PixelAvatar member={member} kind="working" size={80} />);
  const svg = container.querySelector("svg")!;
  expect(svg.getAttribute("viewBox")).toBe("0 0 32 40");
  expect(svg.getAttribute("aria-hidden")).toBe("true");
  expect(svg.getAttribute("data-kind")).toBe("working");
  expect(container.querySelector('[data-accessory="pencil"]')).toBeTruthy();
});
it("provides a complete fallback for missing older metadata", () => {
  const { container } = render(<PixelAvatar member={{ ...member, accessory: undefined, skin: undefined }} kind="unknown" />);
  expect(container.querySelector("svg rect")).toBeTruthy();
  expect(container.querySelector("img")).toBeNull();
});
