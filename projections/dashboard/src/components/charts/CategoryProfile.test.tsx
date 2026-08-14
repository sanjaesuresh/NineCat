import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CategoryKey } from "../../lib/types";
import { CategoryProfile } from "./CategoryProfile";

const zScores: Record<CategoryKey, number> = {
  fg_pct: 0.4,
  ft_pct: -0.2,
  tpm: 1.1,
  pts: 1.8,
  reb: -0.5,
  ast: 0.9,
  stl: 0.3,
  blk: -0.8,
  tov: -0.4,
};

describe("CategoryProfile", () => {
  it("renders all nine category bars given fixture z-scores", () => {
    render(<CategoryProfile zScores={zScores} />);
    expect(screen.getAllByTestId("category-profile-bar")).toHaveLength(9);
  });

  it("renders the muted empty state instead of an empty chart when z-scores are missing", () => {
    render(<CategoryProfile zScores={null} />);
    expect(screen.queryAllByTestId("category-profile-bar")).toHaveLength(0);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });
});
