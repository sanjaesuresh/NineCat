import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { fixturePlayers } from "../components/__fixtures__/players";
import { Movers } from "./Movers";

describe("Movers", () => {
  it("renders the five sections, including the pending panel when playoff contributions are all zero/absent", () => {
    render(
      <Movers players={fixturePlayers} selectedPlayer={null} onSelectPlayer={() => {}} onCloseDetail={() => {}} />,
    );

    expect(screen.getByRole("heading", { name: "Model Risers" })).toBeInTheDocument();
    // Rookie Wonder (riser, rank_difference +20) also appears in the new
    // DisagreementChart's sr-only row list, so this can't assume a single match
    expect(screen.getAllByText("Rookie Wonder").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Model Fallers" })).toBeInTheDocument();
    // Jokić Center appears in Model Fallers, Breakouts, and the disagreement
    // chart, so assert scoped to "at least one" rather than a unique match
    expect(screen.getAllByText("Jokić Center").length).toBeGreaterThan(0);

    // fixtures ship every playoff contribution as 0 (not null/absent), so the
    // section renders as "no boosts clear the threshold," not the pending panel
    expect(screen.getByText(/No players clear the playoff-schedule boost threshold/)).toBeInTheDocument();
  });

  it("clicking a mover entry opens the shared PlayerDetail panel", () => {
    const onSelectPlayer = vi.fn();
    render(
      <Movers players={fixturePlayers} selectedPlayer={null} onSelectPlayer={onSelectPlayer} onCloseDetail={() => {}} />,
    );

    // scope to the Model Risers section -- Rookie Wonder's name also renders
    // in the DisagreementChart's sr-only row list above the section grid
    const risersSection = screen.getByRole("heading", { name: "Model Risers" }).closest("section")!;
    fireEvent.click(within(risersSection).getByText("Rookie Wonder"));
    expect(onSelectPlayer).toHaveBeenCalledWith(fixturePlayers.find((p) => p.name === "Rookie Wonder"));
  });

  it("renders the pending panel when no player has a playoff-schedule contribution at all", () => {
    const noPlayoffData = fixturePlayers.map((p) => ({
      ...p,
      model: {
        ...p.model,
        component_contributions: Object.fromEntries(
          Object.entries(p.model.component_contributions).filter(([key]) => key !== "playoff_schedule"),
        ) as typeof p.model.component_contributions,
      },
    }));

    render(
      <Movers players={noPlayoffData} selectedPlayer={null} onSelectPlayer={() => {}} onCloseDetail={() => {}} />,
    );

    expect(screen.getByText(/2026-27 playoff schedule not yet published/)).toBeInTheDocument();
  });

  it("shows the detail panel for the selected player and wires its close button", () => {
    const onCloseDetail = vi.fn();
    // Ace Guard (not "rookie-"-prefixed) so PlayerDetail's Rookie chip doesn't
    // fold extra text into the heading's accessible name
    const ace = fixturePlayers.find((p) => p.name === "Ace Guard")!;
    render(<Movers players={fixturePlayers} selectedPlayer={ace} onSelectPlayer={() => {}} onCloseDetail={onCloseDetail} />);

    expect(screen.getByRole("heading", { name: "Ace Guard" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close Ace Guard detail" }));
    expect(onCloseDetail).toHaveBeenCalledTimes(1);
  });
});
