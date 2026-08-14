import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RankingsTable } from "./RankingsTable";
import { fixturePlayers } from "./__fixtures__/players";

function getBodyRows() {
  const table = screen.getByRole("table");
  return within(table).getAllByRole("row").slice(1); // drop header row
}

describe("RankingsTable", () => {
  it("renders rows sorted by final_rank ascending by default", () => {
    render(<RankingsTable players={fixturePlayers} selectedPlayerId={null} onSelectPlayer={() => {}} />);
    const rows = getBodyRows();
    expect(within(rows[0]).getByText("Ace Guard")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Jokić Center")).toBeInTheDocument();
    expect(within(rows[5]).getByText("Two-Way Big")).toBeInTheDocument();
  });

  it("sorts by GP descending after two clicks on the GP header (asc, then desc)", () => {
    render(<RankingsTable players={fixturePlayers} selectedPlayerId={null} onSelectPlayer={() => {}} />);
    const gpHeaderButton = screen.getByRole("button", { name: /GP/ });
    fireEvent.click(gpHeaderButton); // GP ascending
    fireEvent.click(gpHeaderButton); // GP descending

    const rows = getBodyRows();
    const names = rows.map((row) => within(row).getAllByRole("cell")[1].textContent);
    // GP: Forward Star 75, Ace Guard 70, Rookie Wonder 65, Jokić Center 60, Two-Way Big 55, Bench Guard 40
    expect(names[0]).toContain("Forward Star");
    expect(names[1]).toContain("Ace Guard");
    expect(names[names.length - 1]).toContain("Bench Guard");
  });

  it("marks the sorted column header with aria-sort", () => {
    render(<RankingsTable players={fixturePlayers} selectedPlayerId={null} onSelectPlayer={() => {}} />);
    const rankHeader = screen.getByRole("columnheader", { name: /Rank/ });
    expect(rankHeader).toHaveAttribute("aria-sort", "ascending");

    fireEvent.click(screen.getByRole("button", { name: /GP/ }));
    expect(screen.getByRole("columnheader", { name: /GP/ })).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getByRole("columnheader", { name: /Rank/ })).toHaveAttribute("aria-sort", "none");
  });

  it("renders injury risk chips with readable label text", () => {
    render(<RankingsTable players={fixturePlayers} selectedPlayerId={null} onSelectPlayer={() => {}} />);
    expect(screen.getAllByText("High")).not.toHaveLength(0); // Forward Star, injury_risk_label: "high"
    expect(screen.getAllByText("Low").length).toBeGreaterThan(0);
  });

  it("column picker toggles a z-score column on and off", () => {
    render(<RankingsTable players={fixturePlayers} selectedPlayerId={null} onSelectPlayer={() => {}} />);
    expect(screen.queryByRole("columnheader", { name: /PTS z/ })).not.toBeInTheDocument();

    // real browsers hide a closed <details>'s content from click/focus; open
    // it first so this test exercises the actual interaction path
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /PTS z/ }));
    expect(screen.getByRole("columnheader", { name: /PTS z/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /PTS z/ }));
    expect(screen.queryByRole("columnheader", { name: /PTS z/ })).not.toBeInTheDocument();
  });

  it("selects a row via the Enter key", () => {
    const onSelectPlayer = vi.fn();
    render(<RankingsTable players={fixturePlayers} selectedPlayerId={null} onSelectPlayer={onSelectPlayer} />);
    const rows = getBodyRows();
    rows[0].focus();
    fireEvent.keyDown(rows[0], { key: "Enter" });
    expect(onSelectPlayer).toHaveBeenCalledWith(fixturePlayers.find((p) => p.name === "Ace Guard"));
  });

  it("selects a row via the Space key", () => {
    const onSelectPlayer = vi.fn();
    render(<RankingsTable players={fixturePlayers} selectedPlayerId={null} onSelectPlayer={onSelectPlayer} />);
    const rows = getBodyRows();
    fireEvent.keyDown(rows[1], { key: " " });
    expect(onSelectPlayer).toHaveBeenCalledTimes(1);
  });

  it("renders the Playoff Sched letter grade for an even 4/4/4 window and an em-dash for a null schedule, sorting nulls last in both directions", () => {
    render(<RankingsTable players={fixturePlayers} selectedPlayerId={null} onSelectPlayer={() => {}} />);
    const rows = getBodyRows();

    const gradeRow = rows.find((row) => within(row).queryByText("Playoff Grade A"));
    expect(gradeRow).toBeDefined();
    const gradeCell = within(gradeRow as HTMLElement).getAllByRole("cell")[7]; // Playoff Sched column
    expect(gradeCell).toHaveTextContent("A+ (12)");

    // "No Playoff Data" has schedule.week_games: null (fixture builder
    // default), so its grade cell is the "unknown, not zero" em-dash case
    const noScheduleRow = rows.find((row) => within(row).queryByText("No Playoff Data"));
    expect(noScheduleRow).toBeDefined();
    const noScheduleCell = within(noScheduleRow as HTMLElement).getAllByRole("cell")[7];
    expect(noScheduleCell).toHaveTextContent("—");

    const gradeHeaderButton = screen.getByRole("button", { name: /Playoff Sched/ });

    fireEvent.click(gradeHeaderButton); // Playoff Sched ascending
    let sortedRows = getBodyRows();
    expect(within(sortedRows[sortedRows.length - 1]).getByText("No Playoff Data")).toBeInTheDocument();

    fireEvent.click(gradeHeaderButton); // Playoff Sched descending
    sortedRows = getBodyRows();
    expect(within(sortedRows[sortedRows.length - 1]).getByText("No Playoff Data")).toBeInTheDocument();
  });

  it("marks the selected row aria-selected", () => {
    render(
      <RankingsTable players={fixturePlayers} selectedPlayerId="ace-guard" onSelectPlayer={() => {}} />,
    );
    const rows = getBodyRows();
    expect(rows[0]).toHaveAttribute("aria-selected", "true");
    expect(rows[1]).toHaveAttribute("aria-selected", "false");
  });
});
