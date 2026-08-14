import { describe, expect, it } from "vitest";
import { fixturePlayers } from "../components/__fixtures__/players";
import type { CategoryKey, Player } from "../lib/types";
import { breakouts, computeMovers, injuryDiscounts, modelFallers, modelRisers, playoffBoosts, playoffDataAvailable } from "./moversData";

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

/** Local fixture builder (mirrors the pattern in lib/recompute.test.ts) so
 * each test only overrides the handful of fields it's actually verifying the
 * math of, rather than reaching for the shared __fixtures__/players.ts set
 * whose values don't hit the exact boundary/tie-break cases below. */
function makePlayer(opts: {
  id: string;
  name: string;
  finalRank?: number;
  consensusRank?: number | null;
  rankDifference?: number | null;
  perGameValue?: number;
  availabilityAdjustedValue?: number;
  roleChangeScore?: number;
  minutesDelta?: number;
  playoffContribution?: number | null | "absent";
}): Player {
  const contributions: Record<string, number> = {
    per_game: 0,
    availability_adjusted: 0,
    expected_games: 0,
    role_usage: 0,
    consensus: 0,
    team_environment: 0,
    category_scarcity: 0,
  };
  if (opts.playoffContribution === undefined) {
    contributions.playoff_schedule = 0;
  } else if (opts.playoffContribution !== "absent" && opts.playoffContribution !== null) {
    contributions.playoff_schedule = opts.playoffContribution;
  }
  // "absent"/null both leave the key out entirely, matching the real
  // pipeline export's behavior for a player with no schedule data.

  return {
    rank: opts.finalRank ?? 0,
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
      availability_adjusted_value: opts.availabilityAdjustedValue ?? 0,
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
      role_change_score: opts.roleChangeScore ?? 0,
      direction: "neutral",
      minutes_delta: opts.minutesDelta ?? 0,
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
      consensus_rank: opts.consensusRank ?? null,
      sources_used: 0,
      rank_variance: null,
      per_source: {},
      rank_difference: opts.rankDifference ?? null,
      flag: "none",
    },
    model: {
      model_rank: 0,
      final_rank: opts.finalRank ?? 0,
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
      component_contributions: contributions as Player["model"]["component_contributions"],
    },
    analysis: { strengths: [], risks: [], explanation: "" },
    sources: [],
  };
}

describe("modelRisers / modelFallers", () => {
  it("includes a player exactly at the +15 riser threshold and excludes one just below it", () => {
    const atThreshold = makePlayer({ id: "a", name: "At Threshold", finalRank: 10, consensusRank: 25, rankDifference: 15 });
    const belowThreshold = makePlayer({ id: "b", name: "Below Threshold", finalRank: 10, consensusRank: 24, rankDifference: 14 });

    const risers = modelRisers([atThreshold, belowThreshold]);

    expect(risers.map((r) => r.player.name)).toEqual(["At Threshold"]);
    expect(risers[0].detail).toBe("#10 model vs #25 consensus");
  });

  it("includes a player exactly at the -15 faller threshold and excludes one just above it", () => {
    const atThreshold = makePlayer({ id: "c", name: "At Threshold", finalRank: 40, consensusRank: 25, rankDifference: -15 });
    const aboveThreshold = makePlayer({ id: "d", name: "Above Threshold", finalRank: 40, consensusRank: 26, rankDifference: -14 });

    const fallers = modelFallers([atThreshold, aboveThreshold]);

    expect(fallers.map((r) => r.player.name)).toEqual(["At Threshold"]);
  });

  it("sorts risers descending by rank_difference and caps at 8", () => {
    const players = Array.from({ length: 10 }, (_, i) =>
      makePlayer({ id: `p${i}`, name: `Player ${i}`, consensusRank: 50, rankDifference: 15 + i }),
    );

    const risers = modelRisers(players);

    expect(risers).toHaveLength(8);
    expect(risers[0].player.name).toBe("Player 9"); // rank_difference 24, the largest
    expect(risers.map((r) => r.player.name)).toContain("Player 2"); // rank_difference 17, still top 8
    expect(risers.map((r) => r.player.name)).not.toContain("Player 0"); // rank_difference 15, pushed out by the cap
  });

  it("uses the real dataset shape from __fixtures__/players.ts: Jokić Center (-18) is a faller, Rookie Wonder (+20) is a riser", () => {
    const risers = modelRisers(fixturePlayers);
    const fallers = modelFallers(fixturePlayers);

    expect(risers.map((r) => r.player.name)).toEqual(["Rookie Wonder"]);
    expect(fallers.map((r) => r.player.name)).toEqual(["Jokić Center"]);
  });

  it("never includes a null rank_difference (no_consensus players)", () => {
    const noConsensus = makePlayer({ id: "e", name: "No Consensus", rankDifference: null });
    expect(modelRisers([noConsensus])).toEqual([]);
    expect(modelFallers([noConsensus])).toEqual([]);
  });
});

describe("injuryDiscounts", () => {
  it("hand-verified rank math: a player who is #1 by per-game value but falls to #4 by availability-adjusted value shows a drop of 3", () => {
    const star = makePlayer({ id: "star", name: "Star", perGameValue: 100, availabilityAdjustedValue: 10 });
    const b = makePlayer({ id: "b", name: "B", perGameValue: 90, availabilityAdjustedValue: 40 });
    const c = makePlayer({ id: "c", name: "C", perGameValue: 80, availabilityAdjustedValue: 30 });
    const d = makePlayer({ id: "d", name: "D", perGameValue: 70, availabilityAdjustedValue: 20 });
    // per-game order: Star(100) B(90) C(80) D(70) -> Star is #1
    // availability order: B(40) C(30) D(20) Star(10) -> Star is #4, drop = 4 - 1 = 3

    const discounts = injuryDiscounts([star, b, c, d]);

    const starEntry = discounts.find((entry) => entry.player.player_id === "star");
    expect(starEntry).toBeUndefined(); // drop of 3 is below the >=5 threshold
    expect(discounts).toEqual([]);
  });

  it("surfaces a drop that clears the >=5 threshold with the exact before/after ranks in the detail text", () => {
    // 6 players: "faller" is #1 by per-game but drops to #6 by availability
    // (drop = 5, exactly at the threshold), the other 5 are unaffected filler.
    const faller = makePlayer({ id: "faller", name: "Faller", perGameValue: 100, availabilityAdjustedValue: 1 });
    const filler = [2, 3, 4, 5, 6].map((n) =>
      makePlayer({ id: `f${n}`, name: `Filler ${n}`, perGameValue: 100 - n, availabilityAdjustedValue: 100 - n }),
    );

    const discounts = injuryDiscounts([faller, ...filler]);

    expect(discounts).toHaveLength(1);
    expect(discounts[0].player.name).toBe("Faller");
    expect(discounts[0].detail).toBe("−5 spots to availability rank (#1 → #6)");
  });
});

describe("playoffBoosts / playoffDataAvailable", () => {
  it("reports unavailable when every player's playoff contribution is null/absent (current pipeline reality)", () => {
    const players = [
      makePlayer({ id: "a", name: "A", playoffContribution: null }),
      makePlayer({ id: "b", name: "B", playoffContribution: "absent" }),
    ];

    expect(playoffDataAvailable(players)).toBe(false);
    expect(playoffBoosts(players)).toEqual([]);
  });

  it("sorts by contribution descending, requires > 0, and reports data as available once any contribution is present", () => {
    const high = makePlayer({ id: "high", name: "High", playoffContribution: 0.8 });
    const low = makePlayer({ id: "low", name: "Low", playoffContribution: 0.2 });
    const zero = makePlayer({ id: "zero", name: "Zero", playoffContribution: 0 });
    const negative = makePlayer({ id: "neg", name: "Negative", playoffContribution: -0.1 });

    const boosts = playoffBoosts([low, high, zero, negative]);

    expect(boosts.map((b) => b.player.name)).toEqual(["High", "Low"]);
    expect(playoffDataAvailable([low, high, zero, negative])).toBe(true);
  });
});

describe("breakouts", () => {
  it("excludes a player at the 0.05 boundary (requires strictly greater than)", () => {
    const atThreshold = makePlayer({ id: "a", name: "At Threshold", roleChangeScore: 0.05 });
    const aboveThreshold = makePlayer({ id: "b", name: "Above Threshold", roleChangeScore: 0.051 });

    const result = breakouts([atThreshold, aboveThreshold]);

    expect(result.map((r) => r.player.name)).toEqual(["Above Threshold"]);
  });

  it("breaks a role_change_score tie by minutes_delta descending", () => {
    const lowMinutes = makePlayer({ id: "a", name: "Low Minutes", roleChangeScore: 0.2, minutesDelta: 1.0 });
    const highMinutes = makePlayer({ id: "b", name: "High Minutes", roleChangeScore: 0.2, minutesDelta: 5.0 });

    const result = breakouts([lowMinutes, highMinutes]);

    expect(result.map((r) => r.player.name)).toEqual(["High Minutes", "Low Minutes"]);
  });

  it("sorts primarily by role_change_score descending, tiebreak notwithstanding", () => {
    const bigScore = makePlayer({ id: "a", name: "Big Score", roleChangeScore: 0.4, minutesDelta: 0.5 });
    const smallScoreBigMinutes = makePlayer({ id: "b", name: "Small Score Big Minutes", roleChangeScore: 0.1, minutesDelta: 10 });

    const result = breakouts([smallScoreBigMinutes, bigScore]);

    expect(result.map((r) => r.player.name)).toEqual(["Big Score", "Small Score Big Minutes"]);
  });
});

describe("computeMovers", () => {
  it("computes all five sections in one pass over the shared fixture pool", () => {
    const movers = computeMovers(fixturePlayers);

    expect(movers.risers.map((r) => r.player.name)).toEqual(["Rookie Wonder"]);
    expect(movers.fallers.map((r) => r.player.name)).toEqual(["Jokić Center"]);
    expect(movers.playoffDataAvailable).toBe(true); // fixtures default every contribution to 0, not null/absent
    expect(movers.playoffBoosts).toEqual([]); // ...but none clear the > 0 threshold
    expect(movers.breakouts.map((r) => r.player.name)).toEqual(["Jokić Center", "Detail Rich"]);
  });
});
