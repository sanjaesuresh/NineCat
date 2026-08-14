import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RankCompare } from "./RankCompare";

describe("RankCompare", () => {
  it("renders our rank, model rank, consensus rank, and per-source rows, noting imputed sources", () => {
    render(
      <RankCompare
        modelRank={20}
        finalRank={8}
        consensusRank={22}
        perSource={{ ESPN: { rank: 18, imputed: false }, Rotowire: { rank: 26, imputed: true } }}
      />,
    );
    const bars = screen.getAllByTestId("rank-compare-bar");
    expect(bars).toHaveLength(5); // Our Rank, Model Rank, Consensus, ESPN, Rotowire
    expect(bars.some((b) => b.textContent?.includes("imputed"))).toBe(true);
  });

  it("renders the empty state when there is no rank data at all", () => {
    render(<RankCompare modelRank={null} finalRank={null} consensusRank={null} perSource={{}} />);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });
});
