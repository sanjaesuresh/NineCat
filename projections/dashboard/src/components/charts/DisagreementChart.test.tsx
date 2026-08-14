import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fixturePlayers } from "../__fixtures__/players";
import { DisagreementChart } from "./DisagreementChart";

describe("DisagreementChart", () => {
  it("renders paired model rank / consensus rank values for the players crossing the +-15 threshold", () => {
    render(<DisagreementChart players={fixturePlayers} />);

    const rows = screen.getAllByTestId("disagreement-chart-row");
    // only jokic-center (rank_difference -18) and rookie-wonder (+20) clear
    // the +-15 threshold in the fixture set
    expect(rows).toHaveLength(2);

    // sorted by |rank_difference| descending: Rookie Wonder (20) before Jokić Center (18)
    expect(rows[0].textContent).toContain("Rookie Wonder");
    expect(rows[0].textContent).toContain("model rank 0");
    expect(rows[0].textContent).toContain("consensus rank 45");

    expect(rows[1].textContent).toContain("Jokić Center");
    expect(rows[1].textContent).toContain("model rank 0");
    expect(rows[1].textContent).toContain("consensus rank 20");
  });

  it("includes the sr-only full player name for each row, not just the truncated axis label", () => {
    render(<DisagreementChart players={fixturePlayers} />);

    expect(screen.getByText(/Rookie Wonder: model rank/)).toBeInTheDocument();
    expect(screen.getByText(/Jokić Center: model rank/)).toBeInTheDocument();
  });

  it("renders the empty state when no player crosses the +-15 rank-difference threshold", () => {
    const noDisagreement = fixturePlayers.filter(
      (p) => p.player_id !== "jokic-center" && p.player_id !== "rookie-wonder",
    );
    render(<DisagreementChart players={noDisagreement} />);

    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.queryByTestId("disagreement-chart-row")).not.toBeInTheDocument();
  });
});
