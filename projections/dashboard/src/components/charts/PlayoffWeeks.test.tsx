import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlayoffWeeks } from "./PlayoffWeeks";

describe("PlayoffWeeks", () => {
  it("renders one bar per scheduled week", () => {
    render(<PlayoffWeeks weekGames={{ "19": 4, "20": 2, "21": 3 }} />);
    expect(screen.getAllByTestId("playoff-week-bar")).toHaveLength(3);
  });

  it("renders the empty state instead of a zeroed chart when the schedule isn't published yet", () => {
    render(<PlayoffWeeks weekGames={null} />);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });
});
