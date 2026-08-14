import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { extractDefaultWeights } from "../lib/recompute";
import type { CategoryKey, CompositeWeights, Dataset, Player } from "../lib/types";
import { Settings } from "./Settings";

const ZERO_CATEGORIES: Record<CategoryKey, number> = {
  fg_pct: 0,
  ft_pct: 0,
  tpm: 0,
  pts: 0,
  reb: 0,
  ast: 0,
  stl: 0,
  blk: 0,
  tov: 0,
};

const DEFAULT_WEIGHTS: CompositeWeights = {
  per_game: 0.4,
  availability_adjusted: 0.2,
  expected_games: 0.1,
  role_usage: 0.1,
  playoff_schedule: 0.05,
  consensus: 0.05,
  team_environment: 0.05,
  category_scarcity: 0.05,
};

/** Local fixture builder (same pattern as lib/recompute.test.ts): every
 * component_score defaults to 0 so a player's score is driven entirely by
 * the one or two components the test overrides -- makes the re-rank math
 * hand-verifiable regardless of what the other 6 sliders are set to. */
function makePlayer(opts: { id: string; name: string; finalRank: number; componentScores: Partial<Record<string, number>> }): Player {
  const scores = {
    per_game: 0,
    availability_adjusted: 0,
    expected_games: 0,
    role_usage: 0,
    playoff_schedule: 0,
    consensus: 0,
    team_environment: 0,
    category_scarcity: 0,
    ...opts.componentScores,
  } as Player["model"]["component_scores"];

  return {
    rank: opts.finalRank,
    player_id: opts.id,
    name: opts.name,
    team: "TST",
    positions: ["PG"],
    age: 25,
    projection: {
      games: 70,
      minutes: 30,
      points: 20,
      rebounds: 5,
      assists: 5,
      steals: 1,
      blocks: 1,
      three_pm: 2,
      fg_pct: 0.5,
      ft_pct: 0.8,
      turnovers: 2,
      fga: 15,
      fta: 5,
      fgm: 7,
      ftm: 4,
    },
    fantasy: {
      per_game_zscores: ZERO_CATEGORIES,
      per_game_value: 0,
      availability_adjusted_value: 0,
      regular_season_value: 0,
      playoff_value: 0,
      combined_value: 0,
      final_score: 0,
      punt_values: ZERO_CATEGORIES,
      scarcity_score: 0,
    },
    availability: {
      raw_projected_games: 70,
      injury_adjusted_games: 70,
      injury_risk_score: 0,
      injury_risk_label: "low",
      availability_probability: 1,
    },
    role: {
      role_change_score: 0,
      direction: "neutral",
      minutes_delta: 0,
      usage_delta: 0,
      minutes_projection: 30,
      starter_probability: null,
      team_changed: false,
      pace_multiplier: 1,
    },
    schedule: {
      week_games: null,
      playoff_games: null,
      playoff_b2bs: null,
      playoff_schedule_score: null,
      expected_playoff_games: null,
      windows: {},
    },
    consensus: {
      consensus_rank: null,
      sources_used: 0,
      rank_variance: null,
      per_source: {},
      rank_difference: null,
      flag: "no_consensus",
    },
    model: {
      model_rank: opts.finalRank,
      final_rank: opts.finalRank,
      confidence: 50,
      confidence_band: "MEDIUM",
      component_scores: scores,
      component_contributions: {
        per_game: 0,
        availability_adjusted: 0,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
    },
    analysis: { strengths: [], risks: [], explanation: "" },
    sources: [],
  };
}

// 3-fixture pool: Alice scores entirely on per_game, Bob entirely on
// availability_adjusted, Cara scores 0 everywhere (always last regardless of
// weights). Under DEFAULT_WEIGHTS (per_game .4 > availability_adjusted .2),
// Alice(.4*10=4) ranks above Bob(.2*10=2) ranks above Cara(0).
const alice = makePlayer({ id: "alice", name: "Alice", finalRank: 1, componentScores: { per_game: 10 } });
const bob = makePlayer({ id: "bob", name: "Bob", finalRank: 2, componentScores: { availability_adjusted: 10 } });
const cara = makePlayer({ id: "cara", name: "Cara", finalRank: 3, componentScores: {} });

function buildDataset(): Dataset {
  return {
    season: "2026-27",
    projection_date: "2026-08-01",
    last_updated: "2026-08-01T00:00:00Z",
    schedule_available: false,
    playoff_window_force_unavailable: false,
    candidate_windows: ["17-19", "18-20", "19-21", "20-22", "21-23", "22-24"],
    default_window: "19-21",
    settings: {
      value_split: { regular_season: 0.7, playoff: 0.3 },
      composite_weights: DEFAULT_WEIGHTS,
      // fields Settings.tsx doesn't read are omitted -- component only
      // touches settings.value_split and settings.composite_weights
    } as Dataset["settings"],
    players: [alice, bob, cara],
  };
}

/** App owns weights/windowKey as controlled state and passes them down --
 * this harness mirrors that so Settings' interactive tests (slider drag,
 * reset) still exercise real state updates through the props boundary. */
function ControlledSettings({ dataset }: { dataset: Dataset }) {
  const [weights, setWeights] = useState<CompositeWeights>(extractDefaultWeights(dataset));
  return <Settings dataset={dataset} weights={weights} onWeightsChange={setWeights} windowKey="19-21" />;
}

function top25Rows() {
  const table = screen.getByRole("table", { name: /top 25 players/i });
  return within(table).getAllByRole("row").slice(1); // drop header row
}

describe("Settings", () => {
  it("renders the shipped order under default weights: Alice > Bob > Cara", () => {
    render(<ControlledSettings dataset={buildDataset()} />);
    const rows = top25Rows();
    expect(within(rows[0]).getByText("Alice")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Bob")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Cara")).toBeInTheDocument();
  });

  it("raising the availability_adjusted slider to max flips Bob above Alice, as hand math predicts", async () => {
    render(<ControlledSettings dataset={buildDataset()} />);

    const slider = screen.getByLabelText("Availability-adjusted");
    // hand math: Alice's score is fixed at .4*10=4 regardless of this slider
    // (her only nonzero component is per_game); raising availability_adjusted
    // to 1.0 makes Bob's score 1.0*10=10, which now beats Alice's 4
    fireEvent.change(slider, { target: { value: "1" } });

    await waitFor(
      () => {
        const rows = top25Rows();
        expect(within(rows[0]).getByText("Bob")).toBeInTheDocument();
      },
      { timeout: 1000 },
    );

    const rows = top25Rows();
    expect(within(rows[1]).getByText("Alice")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Cara")).toBeInTheDocument();
  });

  it("reset restores the shipped default order and weight values immediately", async () => {
    render(<ControlledSettings dataset={buildDataset()} />);

    const slider = screen.getByLabelText("Availability-adjusted") as HTMLInputElement;
    fireEvent.change(slider, { target: { value: "1" } });

    await waitFor(() => {
      const rows = top25Rows();
      expect(within(rows[0]).getByText("Bob")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));

    expect(slider.value).toBe("0.2");
    const rows = top25Rows();
    expect(within(rows[0]).getByText("Alice")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Bob")).toBeInTheDocument();
  });

  it("shows the read-only regular/playoff split with a pipeline re-run note", () => {
    render(<ControlledSettings dataset={buildDataset()} />);
    expect(screen.getByText(/Regular season/)).toBeInTheDocument();
    expect(screen.getByText("70%")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();
    expect(screen.getByText(/re-run it to see new numbers here/)).toBeInTheDocument();
  });
});
