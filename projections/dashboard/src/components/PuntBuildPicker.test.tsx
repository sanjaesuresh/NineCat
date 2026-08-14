import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PuntBuildPicker } from "./PuntBuildPicker";

describe("PuntBuildPicker", () => {
  it("shows 'Punt: none' when nothing is selected", () => {
    render(<PuntBuildPicker punts={[]} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Punt: none" })).toBeInTheDocument();
  });

  it("button label reflects selections, joined by comma in canonical category order", () => {
    render(<PuntBuildPicker punts={["tov", "ft_pct"]} onChange={() => {}} />);
    // canonical order is FG%..TO -> ft_pct before tov regardless of array order passed in
    expect(screen.getByRole("button", { name: "Punt: FT%, TO" })).toBeInTheDocument();
  });

  it("aria-expanded toggles open/closed, and Escape closes the popover", () => {
    render(<PuntBuildPicker punts={[]} onChange={() => {}} />);
    const button = screen.getByRole("button", { name: "Punt: none" });
    expect(button).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Punt: none" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("checkbox", { name: "FT%" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Punt: none" })).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on an outside click", () => {
    render(
      <div>
        <button type="button">outside</button>
        <PuntBuildPicker punts={[]} onChange={() => {}} />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Punt: none" }));
    expect(screen.getByRole("button", { name: "Punt: none" })).toHaveAttribute("aria-expanded", "true");

    fireEvent.mouseDown(screen.getByRole("button", { name: "outside" }));
    expect(screen.getByRole("button", { name: "Punt: none" })).toHaveAttribute("aria-expanded", "false");
  });

  it("checking multiple categories composes -- no cap on selections", () => {
    const onChange = vi.fn();
    render(<PuntBuildPicker punts={["ft_pct"]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Punt: FT%" }));

    fireEvent.click(screen.getByRole("checkbox", { name: "AST" }));
    expect(onChange).toHaveBeenCalledWith(["ft_pct", "ast"]);
  });

  it("unchecking a category removes only that one, preserving the rest", () => {
    const onChange = vi.fn();
    render(<PuntBuildPicker punts={["ft_pct", "ast", "stl"]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Punt: FT%, AST, ST" }));

    fireEvent.click(screen.getByRole("checkbox", { name: "AST" }));
    expect(onChange).toHaveBeenCalledWith(["ft_pct", "stl"]);
  });
});
