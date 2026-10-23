import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
vi.mock("next/navigation", () => ({ usePathname: () => "/jobs/abc" }));
import { Sidebar } from "./Sidebar";
it("exposes the active section even on a nested route", () => {
  render(<Sidebar />);
  expect(screen.getByRole("navigation", { name: "Navigasi utama" })).toBeTruthy();
  expect(screen.getByRole("link", { name: /Jobs/ }).getAttribute("aria-current")).toBe("page");
});
