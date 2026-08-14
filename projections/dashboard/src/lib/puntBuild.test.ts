import { describe, expect, it } from "vitest";
import { applyPuntBuild, populationZ } from "./puntBuild";
import type { CategoryKey, Player } from "./types";

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

/** Minimal fully-typed fixture Player -- mirrors recompute.test.ts's
 * makePlayer, but exposes per_game_zscores/availability_adjusted_zscores
 * directly since those are what applyPuntBuild actually reads. */
function makePlayer(opts: {
  id: string;
  name: string;
  perGameZscores: Record<CategoryKey, number>;
  availAdjustedZscores?: Record<CategoryKey, number>;
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
      per_game_zscores: opts.perGameZscores,
      per_game_value: Object.values(opts.perGameZscores).reduce((a, b) => a + b, 0),
      availability_adjusted_zscores: opts.availAdjustedZscores,
      availability_adjusted_value: opts.availAdjustedZscores
        ? Object.values(opts.availAdjustedZscores).reduce((a, b) => a + b, 0)
        : 0,
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
      model_rank: 0,
      final_rank: 0,
      confidence: 50,
      confidence_band: "MEDIUM",
      component_scores: {
        per_game: 0,
        availability_adjusted: 0,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
      component_contributions: {},
    },
    analysis: { strengths: [], risks: [], explanation: "" },
    sources: [],
  };
}

describe("populationZ", () => {
  it("standardizes to mean 0 (divide-by-N std, not N-1)", () => {
    const z = populationZ([1, 1, 2]);
    expect(z[0]).toBeCloseTo(-1 / Math.sqrt(2), 9);
    expect(z[1]).toBeCloseTo(-1 / Math.sqrt(2), 9);
    expect(z[2]).toBeCloseTo(Math.sqrt(2), 9);
  });

  it("collapses to all zeros on zero variance (including a single-element pool)", () => {
    expect(populationZ([5, 5, 5])).toEqual([0, 0, 0]);
    expect(populationZ([7])).toEqual([0]);
  });

  it("returns [] for an empty pool", () => {
    expect(populationZ([])).toEqual([]);
  });
});

describe("applyPuntBuild", () => {
  const a = makePlayer({
    id: "a",
    name: "A",
    perGameZscores: { ...ZERO_CATEGORIES, fg_pct: 1, ft_pct: 2 },
  });
  const b = makePlayer({
    id: "b",
    name: "B",
    perGameZscores: { ...ZERO_CATEGORIES, ft_pct: 5, tpm: 1 },
  });
  const c = makePlayer({
    id: "c",
    name: "C",
    perGameZscores: { ...ZERO_CATEGORIES, fg_pct: 2, ft_pct: -3 },
  });

  it("identity fast-path: [] returns the input array by reference", () => {
    const players = [a, b, c];
    expect(applyPuntBuild(players, [])).toBe(players);
  });

  it("punting ft_pct: punted per-game sums are exact, then re-standardized (population z)", () => {
    const [pa, pb, pc] = applyPuntBuild([a, b, c], ["ft_pct"]);

    // hand math: A = fg_pct(1) + everything-else(0) = 1; B = tpm(1) = 1; C = fg_pct(2) = 2
    expect(pa.fantasy.per_game_value).toBeCloseTo(1, 9);
    expect(pb.fantasy.per_game_value).toBeCloseTo(1, 9);
    expect(pc.fantasy.per_game_value).toBeCloseTo(2, 9);

    // population z of [1, 1, 2]: mean 4/3, std sqrt(2)/3
    expect(pa.model.component_scores.per_game).toBeCloseTo(-1 / Math.sqrt(2), 9);
    expect(pb.model.component_scores.per_game).toBeCloseTo(-1 / Math.sqrt(2), 9);
    expect(pc.model.component_scores.per_game).toBeCloseTo(Math.sqrt(2), 9);

    // every other component_score untouched
    expect(pa.model.component_scores.availability_adjusted).toBe(0);
    expect(pa.model.component_scores.category_scarcity).toBe(0);
  });

  it("punting two categories (fg_pct + ft_pct) excludes both from the sum", () => {
    const [pa, pb, pc] = applyPuntBuild([a, b, c], ["fg_pct", "ft_pct"]);

    // A = 0 (only fg_pct/ft_pct were nonzero); B = tpm(1) = 1; C = 0
    expect(pa.fantasy.per_game_value).toBeCloseTo(0, 9);
    expect(pb.fantasy.per_game_value).toBeCloseTo(1, 9);
    expect(pc.fantasy.per_game_value).toBeCloseTo(0, 9);

    // population z of [0, 1, 0]: mean 1/3, std sqrt(2)/3
    expect(pa.model.component_scores.per_game).toBeCloseTo(-1 / Math.sqrt(2), 9);
    expect(pb.model.component_scores.per_game).toBeCloseTo(Math.sqrt(2), 9);
    expect(pc.model.component_scores.per_game).toBeCloseTo(-1 / Math.sqrt(2), 9);
  });

  it("zero-variance edge: every player's punted sum is identical -> every z is 0", () => {
    const d = makePlayer({ id: "d", name: "D", perGameZscores: { ...ZERO_CATEGORIES, ft_pct: 9 } });
    const e = makePlayer({ id: "e", name: "E", perGameZscores: { ...ZERO_CATEGORIES, ft_pct: -4 } });

    // punting the only nonzero category leaves both players at sum 0
    const [pd, pe] = applyPuntBuild([d, e], ["ft_pct"]);
    expect(pd.fantasy.per_game_value).toBe(0);
    expect(pe.fantasy.per_game_value).toBe(0);
    expect(pd.model.component_scores.per_game).toBe(0);
    expect(pe.model.component_scores.per_game).toBe(0);
  });

  it("also punts availability_adjusted_zscores when every player in the pool carries it", () => {
    const withAvail1 = makePlayer({
      id: "x",
      name: "X",
      perGameZscores: ZERO_CATEGORIES,
      availAdjustedZscores: { ...ZERO_CATEGORIES, ft_pct: 4, pts: 1 },
    });
    const withAvail2 = makePlayer({
      id: "y",
      name: "Y",
      perGameZscores: ZERO_CATEGORIES,
      availAdjustedZscores: { ...ZERO_CATEGORIES, ft_pct: -2, pts: 3 },
    });

    const [px, py] = applyPuntBuild([withAvail1, withAvail2], ["ft_pct"]);

    // punted sums: X = pts(1) = 1; Y = pts(3) = 3 -- population z of [1,3]: mean 2, std 1
    expect(px.fantasy.availability_adjusted_value).toBeCloseTo(1, 9);
    expect(py.fantasy.availability_adjusted_value).toBeCloseTo(3, 9);
    expect(px.model.component_scores.availability_adjusted).toBeCloseTo(-1, 9);
    expect(py.model.component_scores.availability_adjusted).toBeCloseTo(1, 9);
  });

  it("leaves availability-adjusted fields untouched pool-wide when any player lacks availability_adjusted_zscores (current export gap)", () => {
    const withAvail = makePlayer({
      id: "x",
      name: "X",
      perGameZscores: ZERO_CATEGORIES,
      availAdjustedZscores: { ...ZERO_CATEGORIES, ft_pct: 4 },
    });
    const withoutAvail = makePlayer({ id: "y", name: "Y", perGameZscores: ZERO_CATEGORIES });

    const [px, py] = applyPuntBuild([withAvail, withoutAvail], ["ft_pct"]);

    // shipped values (0) preserved, not silently recomputed off partial data
    expect(px.fantasy.availability_adjusted_value).toBe(withAvail.fantasy.availability_adjusted_value);
    expect(py.fantasy.availability_adjusted_value).toBe(withoutAvail.fantasy.availability_adjusted_value);
    expect(px.model.component_scores.availability_adjusted).toBe(0);
    // per-game side still fully applies regardless of the availability gap
    expect(px.fantasy.per_game_value).toBe(0);
  });
});
