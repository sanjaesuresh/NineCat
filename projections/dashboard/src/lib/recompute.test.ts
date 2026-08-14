import { describe, expect, it } from "vitest";
import { applyWindow, componentContributions, recomputeScores, weightsEqual } from "./recompute";
import type { CategoryKey, CompositeWeights, Player, WindowProfile } from "./types";

// mirrors the shipped settings.composite_weights in projections/data/players_2026_27.json
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

/** Builds a fully-typed fixture Player, only the fields a given test cares
 * about (component_scores, per_game_value, name) need overriding -- the rest
 * are filled with neutral defaults so every field TypeScript requires exists. */
function makePlayer(opts: {
  id: string;
  name: string;
  componentScores: Player["model"]["component_scores"];
  perGameValue?: number;
  windows?: Record<string, WindowProfile>;
}): Player {
  return {
    rank: 0,
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
      per_game_value: opts.perGameValue ?? 0,
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
      windows: opts.windows ?? {},
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
      model_rank: 0,
      final_rank: 0,
      confidence: 50,
      confidence_band: "MEDIUM",
      component_scores: opts.componentScores,
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

describe("recomputeScores", () => {
  it("(a) reproduces the shipped ranking order and scores under default weights", () => {
    // hand math: Alice = .4*1 + .2*5 = 1.4; Bob = .4*2 = 0.8; Cara = .4*3 = 1.2
    const alice = makePlayer({
      id: "1",
      name: "Alice",
      perGameValue: 50,
      componentScores: {
        per_game: 1,
        availability_adjusted: 5,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
    });
    const bob = makePlayer({
      id: "2",
      name: "Bob",
      perGameValue: 30,
      componentScores: {
        per_game: 2,
        availability_adjusted: 0,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
    });
    const cara = makePlayer({
      id: "3",
      name: "Cara",
      perGameValue: 40,
      componentScores: {
        per_game: 3,
        availability_adjusted: 0,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
    });

    const ranked = recomputeScores([alice, bob, cara], DEFAULT_WEIGHTS);

    expect(ranked.map((r) => r.player.name)).toEqual(["Alice", "Cara", "Bob"]);
    expect(ranked.map((r) => r.newRank)).toEqual([1, 2, 3]);
    expect(ranked[0].newScore).toBeCloseTo(1.4, 9);
    expect(ranked[1].newScore).toBeCloseTo(1.2, 9);
    expect(ranked[2].newScore).toBeCloseTo(0.8, 9);
  });

  it("(b) shifting all weight to per_game reorders as hand math predicts", () => {
    const alice = makePlayer({
      id: "1",
      name: "Alice",
      componentScores: {
        per_game: 1,
        availability_adjusted: 5,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
    });
    const bob = makePlayer({
      id: "2",
      name: "Bob",
      componentScores: {
        per_game: 2,
        availability_adjusted: 0,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
    });
    const cara = makePlayer({
      id: "3",
      name: "Cara",
      componentScores: {
        per_game: 3,
        availability_adjusted: 0,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
    });

    const allPerGameWeight: CompositeWeights = {
      per_game: 1,
      availability_adjusted: 0,
      expected_games: 0,
      role_usage: 0,
      playoff_schedule: 0,
      consensus: 0,
      team_environment: 0,
      category_scarcity: 0,
    };

    const ranked = recomputeScores([alice, bob, cara], allPerGameWeight);

    // reversed from (a): pure per_game score is Cara(3) > Bob(2) > Alice(1)
    expect(ranked.map((r) => r.player.name)).toEqual(["Cara", "Bob", "Alice"]);
    expect(ranked.map((r) => r.newScore)).toEqual([3, 2, 1]);
  });

  it("(c) null playoff/consensus components renormalize the remaining weights", () => {
    // playoff_schedule (.05) and consensus (.05) missing -> renorm over the
    // remaining .9 of weight; every present component scores 1, so the
    // weighted sum collapses to (sum of present weights) / 0.9 == 1.0 exactly
    const dana = makePlayer({
      id: "4",
      name: "Dana",
      componentScores: {
        per_game: 1,
        availability_adjusted: 1,
        expected_games: 1,
        role_usage: 1,
        playoff_schedule: null,
        consensus: null,
        team_environment: 1,
        category_scarcity: 1,
      },
    });

    const [ranked] = recomputeScores([dana], DEFAULT_WEIGHTS);

    expect(ranked.newScore).toBeCloseTo(1.0, 9);
  });

  it("(d) ties break by per_game_value, then by player_id (matches composite.py's _rank)", () => {
    // Eve and Frank: identical component_scores (equal newScore), different per_game_value
    const componentScores = {
      per_game: 1,
      availability_adjusted: 0,
      expected_games: 0,
      role_usage: 0,
      playoff_schedule: 0,
      consensus: 0,
      team_environment: 0,
      category_scarcity: 0,
    };
    const eve = makePlayer({ id: "5", name: "Eve", perGameValue: 10, componentScores });
    const frank = makePlayer({ id: "6", name: "Frank", perGameValue: 20, componentScores });
    // Grace and Henry: identical score AND identical per_game_value -> falls through to
    // player_id. IDs are deliberately reversed vs. name-alphabetical order ("2" < "9" but
    // "Grace" < "Henry") so this only passes under id-based tie-break, not name-based.
    const grace = makePlayer({ id: "9", name: "Grace", perGameValue: 5, componentScores });
    const henry = makePlayer({ id: "2", name: "Henry", perGameValue: 5, componentScores });

    const ranked = recomputeScores([eve, frank, grace, henry], DEFAULT_WEIGHTS);

    expect(ranked.map((r) => r.player.player_id)).toEqual(["6", "5", "2", "9"]);
    expect(ranked.map((r) => r.player.name)).toEqual(["Frank", "Eve", "Henry", "Grace"]);
  });
});

describe("weightsEqual", () => {
  const a: CompositeWeights = { ...DEFAULT_WEIGHTS };

  it("is true for two structurally-equal weight objects (different references)", () => {
    expect(weightsEqual(a, { ...DEFAULT_WEIGHTS })).toBe(true);
  });

  it("is false when exactly one component differs", () => {
    expect(weightsEqual(a, { ...DEFAULT_WEIGHTS, per_game: 0.41 })).toBe(false);
  });
});

describe("componentContributions", () => {
  it("renormalizes over present components and sums to the same total recomputeScores produces", () => {
    const dana = makePlayer({
      id: "dana",
      name: "Dana",
      componentScores: {
        per_game: 1,
        availability_adjusted: 1,
        expected_games: 1,
        role_usage: 1,
        playoff_schedule: null,
        consensus: null,
        team_environment: 1,
        category_scarcity: 1,
      },
    });

    const contributions = componentContributions(dana, DEFAULT_WEIGHTS);

    expect(contributions.playoff_schedule).toBeUndefined();
    expect(contributions.consensus).toBeUndefined();
    const total = Object.values(contributions).reduce((sum, v) => sum + v, 0);
    const [ranked] = recomputeScores([dana], DEFAULT_WEIGHTS);
    expect(total).toBeCloseTo(ranked.newScore, 9);
  });

  it("returns an empty object for a degenerate all-zero-weight selection", () => {
    const zeroWeights: CompositeWeights = {
      per_game: 0,
      availability_adjusted: 0,
      expected_games: 0,
      role_usage: 0,
      playoff_schedule: 0,
      consensus: 0,
      team_environment: 0,
      category_scarcity: 0,
    };
    const alice = makePlayer({
      id: "1",
      name: "Alice",
      componentScores: {
        per_game: 1,
        availability_adjusted: 0,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
    });
    expect(componentContributions(alice, zeroWeights)).toEqual({});
  });
});

describe("applyWindow", () => {
  const zeroScores: Player["model"]["component_scores"] = {
    per_game: 0,
    availability_adjusted: 0,
    expected_games: 0,
    role_usage: 0,
    playoff_schedule: 0,
    consensus: 0,
    team_environment: 0,
    category_scarcity: 0,
  };

  const windows: Record<string, WindowProfile> = {
    "19-21": {
      week_games: { "19": 3, "20": 3, "21": 3 },
      playoff_games: 9,
      playoff_b2bs: 2,
      playoff_schedule_score: 1.0,
      expected_playoff_games: 8.0,
      playoff_value_z: 0.5,
    },
    "18-20": {
      week_games: { "18": 4, "19": 3, "20": 3 },
      playoff_games: 10,
      playoff_b2bs: 1,
      playoff_schedule_score: 0.9,
      expected_playoff_games: 9.0,
      playoff_value_z: 2.0,
    },
  };

  it("swaps schedule/fantasy/component_scores to the selected window's values", () => {
    const player = makePlayer({ id: "1", name: "Alice", componentScores: zeroScores, windows });

    const [swapped] = applyWindow([player], "18-20");

    expect(swapped.schedule.week_games).toEqual({ "18": 4, "19": 3, "20": 3 });
    expect(swapped.schedule.playoff_games).toBe(10);
    expect(swapped.schedule.playoff_b2bs).toBe(1);
    expect(swapped.schedule.playoff_schedule_score).toBe(0.9);
    expect(swapped.schedule.expected_playoff_games).toBe(9.0);
    expect(swapped.fantasy.playoff_value).toBe(2.0);
    expect(swapped.model.component_scores.playoff_schedule).toBe(2.0);
    // every other component_score is untouched
    expect(swapped.model.component_scores.per_game).toBe(0);
  });

  it("a window key missing from the player's windows map collapses to the shared null convention", () => {
    const player = makePlayer({ id: "1", name: "Alice", componentScores: zeroScores, windows });

    const [swapped] = applyWindow([player], "22-24"); // not in `windows`

    expect(swapped.schedule.week_games).toBeNull();
    expect(swapped.schedule.playoff_games).toBeNull();
    expect(swapped.fantasy.playoff_value).toBeNull();
    expect(swapped.model.component_scores.playoff_schedule).toBeNull();
  });

  it("swap + recomputeScores re-ranks a 3-player pool as hand math predicts", () => {
    // all weight on playoff_schedule so the window swap is the only thing
    // that can move the ranking; Alice's "18-20" z (2.0) > Bob's (0.5) >
    // Cara's (no windows entry -> null, drops out of the pool entirely)
    const allPlayoffWeight: CompositeWeights = {
      per_game: 0,
      availability_adjusted: 0,
      expected_games: 0,
      role_usage: 0,
      playoff_schedule: 1,
      consensus: 0,
      team_environment: 0,
      category_scarcity: 0,
    };
    const alice = makePlayer({ id: "1", name: "Alice", componentScores: zeroScores, windows });
    const bob = makePlayer({
      id: "2",
      name: "Bob",
      componentScores: zeroScores,
      windows: {
        "18-20": { ...windows["18-20"], playoff_value_z: 0.5 },
      },
    });
    const cara = makePlayer({ id: "3", name: "Cara", componentScores: zeroScores, windows: {} });

    const swapped = applyWindow([alice, bob, cara], "18-20");
    const ranked = recomputeScores(swapped, allPlayoffWeight);

    // Cara's playoff_schedule is null post-swap -- every other component is
    // also 0/null for her, so recomputeScore's weightSum-over-present-keys is
    // 0 and she scores exactly 0, same as if she had a neutral schedule
    expect(ranked.map((r) => r.player.name)).toEqual(["Alice", "Bob", "Cara"]);
    expect(ranked[0].newScore).toBeCloseTo(2.0, 9);
    expect(ranked[1].newScore).toBeCloseTo(0.5, 9);
    expect(ranked[2].newScore).toBeCloseTo(0, 9);
  });
});
