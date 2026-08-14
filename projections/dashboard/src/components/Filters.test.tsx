import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Filters } from "./Filters";
import { defaultFilters } from "./filterPlayers";

describe("Filters", () => {
  it("shows the result count as an aria-live region", () => {
    render(
      <Filters filters={defaultFilters} onChange={() => {}} teams={["LAL", "BOS"]} resultCount={4} totalCount={6} />,
    );
    const status = screen.getByText("4 of 6 players");
    expect(status).toHaveAttribute("aria-live", "polite");
  });

  it("typing in search calls onChange with the new search value", () => {
    const onChange = vi.fn();
    render(
      <Filters filters={defaultFilters} onChange={onChange} teams={["LAL"]} resultCount={6} totalCount={6} />,
    );
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "jokic" } });
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, search: "jokic" });
  });

  it("selecting a position calls onChange with the position set", () => {
    const onChange = vi.fn();
    render(
      <Filters filters={defaultFilters} onChange={onChange} teams={["LAL"]} resultCount={6} totalCount={6} />,
    );
    fireEvent.change(screen.getByLabelText("Position"), { target: { value: "C" } });
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, position: "C" });
  });

  it("toggling an injury risk checkbox adds it to the multi-select list", () => {
    const onChange = vi.fn();
    render(
      <Filters filters={defaultFilters} onChange={onChange} teams={["LAL"]} resultCount={6} totalCount={6} />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "High" }));
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, injuryRisk: ["high"] });
  });

  it("selecting a consensus flag calls onChange with that flag", () => {
    const onChange = vi.fn();
    render(
      <Filters filters={defaultFilters} onChange={onChange} teams={["LAL"]} resultCount={6} totalCount={6} />,
    );
    fireEvent.change(screen.getByLabelText("Consensus flag"), { target: { value: "model_loves" } });
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, consensusFlag: "model_loves" });
  });

  it("Clear all resets to defaultFilters regardless of current state", () => {
    const onChange = vi.fn();
    const dirty = { ...defaultFilters, search: "abc", rookieOnly: true };
    render(<Filters filters={dirty} onChange={onChange} teams={["LAL"]} resultCount={1} totalCount={6} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onChange).toHaveBeenCalledWith(defaultFilters);
  });
});
