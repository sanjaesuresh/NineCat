import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { weekRowTint } from "./charts/chartTheme";
import { fixturePlayers } from "./__fixtures__/players";
import { PlayerDetail } from "./PlayerDetail";

function getFixture(id: string) {
  const player = fixturePlayers.find((p) => p.player_id === id);
  if (!player) throw new Error(`missing fixture ${id}`);
  return player;
}

describe("PlayerDetail", () => {
  it("renders the analysis explanation verbatim and consensus per-source rows including the imputed tag", () => {
    const player = getFixture("detail-rich");
    render(<PlayerDetail player={player} onClose={() => {}} />);

    expect(screen.getByText(player.analysis.explanation)).toBeInTheDocument();

    // consensus per-source rows: "#18" (ESPN, real) and "#26" (Rotowire,
    // imputed) are unique strings in the panel, so they pin down the exact
    // row without also matching the Sources section's plain source-name link
    const espnRow = screen.getAllByRole("listitem").find((li) => li.textContent?.includes("#18"));
    const rotowireRow = screen.getAllByRole("listitem").find((li) => li.textContent?.includes("#26"));
    expect(espnRow).toBeDefined();
    expect(within(espnRow as HTMLElement).queryByText("Imputed")).not.toBeInTheDocument();
    expect(rotowireRow).toBeDefined();
    expect(within(rotowireRow as HTMLElement).getByText("Imputed")).toBeInTheDocument();
  });

  it("renders the schedule pending note instead of zeroed-out week rows when week_games is null", () => {
    const player = getFixture("ace-guard"); // week_games null by default in the fixture builder
    render(<PlayerDetail player={player} onClose={() => {}} />);

    expect(screen.getByText("2026-27 schedule pending")).toBeInTheDocument();
    expect(screen.queryByText(/^Week \d+/)).not.toBeInTheDocument();
    expect(screen.queryByText("0 games")).not.toBeInTheDocument();
    // no computable grade for a null schedule -- no stray badge next to the title
    expect(screen.queryByText(/^[ABCDF][+-]? \(/)).not.toBeInTheDocument();
  });

  it("shows the Playoff Sched grade badge next to the Schedule heading when the window is gradeable", () => {
    const player = getFixture("playoff-grade-a"); // even 4/4/4 window -> A+ (12)
    render(<PlayerDetail player={player} onClose={() => {}} />);

    const heading = screen.getByRole("heading", { name: /Schedule/ });
    expect(within(heading).getByText("A+ (12)")).toBeInTheDocument();
  });

  it("calls onClose when Escape is pressed", () => {
    const onClose = vi.fn();
    render(<PlayerDetail player={getFixture("ace-guard")} onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders an em-dash for a null playoff value instead of 0.00 or crashing", () => {
    const player = getFixture("no-playoff-data");
    render(<PlayerDetail player={player} onClose={() => {}} />);

    const row = screen.getByText("Playoff value").closest("div");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("—")).toBeInTheDocument();
  });

  it("moves focus to the player name heading on open", () => {
    render(<PlayerDetail player={getFixture("detail-rich")} onClose={() => {}} />);
    expect(screen.getByRole("heading", { name: /Detail Rich/ })).toHaveFocus();
  });
});

describe("weekRowTint", () => {
  it("treats >=4 games as favorable", () => {
    expect(weekRowTint(4)).toBe("favorable");
    expect(weekRowTint(5)).toBe("favorable");
  });

  it("treats <=2 games as unfavorable", () => {
    expect(weekRowTint(2)).toBe("unfavorable");
    expect(weekRowTint(0)).toBe("unfavorable");
  });

  it("treats exactly 3 games as neutral (the plain middle)", () => {
    expect(weekRowTint(3)).toBe("neutral");
  });
});
