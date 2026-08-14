import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AvailabilityChart } from "./AvailabilityChart";

describe("AvailabilityChart", () => {
  it("renders the raw, injury-adjusted, and full-season reference bars", () => {
    render(<AvailabilityChart rawProjectedGames={74} injuryAdjustedGames={68} />);
    expect(screen.getAllByTestId("availability-bar")).toHaveLength(3);
  });

  it("renders the empty state when games figures are missing", () => {
    render(<AvailabilityChart rawProjectedGames={null} injuryAdjustedGames={null} />);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });
});
