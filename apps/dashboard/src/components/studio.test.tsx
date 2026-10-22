import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { PromptEditor, Toast } from "./studio";

it("labels the prompt even after an override and exposes its error", () => {
  const change = vi.fn();
  render(
    <PromptEditor
      value="custom"
      defaultValue="default"
      onChange={change}
      onReset={vi.fn()}
      error="Too long"
    />,
  );
  const input = screen.getByRole("textbox", { name: "System prompt", exact: true });
  expect(input.getAttribute("aria-invalid")).toBe("true");
  fireEvent.change(input, { target: { value: "new" } });
  expect(change).toHaveBeenCalledWith("new");
});

it("announces a save message and retains an accessible close control", () => {
  const close = vi.fn();
  render(<Toast toast={{ kind: "ok", text: "Tersimpan" }} onClose={close} />);
  expect(screen.getByRole("status").textContent).toContain("Tersimpan");
  fireEvent.click(screen.getByRole("button", { name: "tutup" }));
  expect(close).toHaveBeenCalledOnce();
});
