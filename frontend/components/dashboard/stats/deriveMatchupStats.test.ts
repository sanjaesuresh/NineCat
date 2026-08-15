import { describe, expect, it } from "vitest";
import type {
  LeagueMatchupResponse,
  MatchupCategoryVerdict,
  MatchupComparisonResult,
  MatchupSide,
  ScheduleCoverage,
} from "@/lib/api";
import { deriveMatchupStats } from "./deriveMatchupStats";

// minimal WeeklyProjectionOut/BuildProfile filler -- every field is required
// on the wire, so tests spell it out explicitly rather than relying on
// partial defaults, matching deriveTeamStats.test.ts's builder convention
function side(overrides: Partial<MatchupSide> & { team_id: number; name: string }): MatchupSide {
  return {
    team_key: `key-${overrides.team_id}`,
    projection: { totals: {}, components: {}, games: 0, player_games: {} },
    build_profile: { totals: {}, labels: {}, means: {} },
    ...overrides,
  };
}

function verdict(overrides: Partial<MatchupCategoryVerdict> & { category: string }): MatchupCategoryVerdict {
  return {
    mine: 0,
    theirs: 0,
    margin: 0,
    verdict: "tie",
    ...overrides,
  };
}

function comparison(
  categories: MatchupCategoryVerdict[],
  overrides: Partial<MatchupComparisonResult> = {},
): MatchupComparisonResult {
  return {
    categories,
    projected_score: [0, 0],
    close_categories: [],
    focus: [],
    ...overrides,
  };
}

function coverage(overrides: Partial<ScheduleCoverage> = {}): ScheduleCoverage {
  return { mine_games: 7, opponent_games: 7, ok: true, ...overrides };
}

function matchup(overrides: Partial<LeagueMatchupResponse> = {}): LeagueMatchupResponse {
  return {
    week: 1,
    week_range: { start_date: "2026-01-05", end_date: "2026-01-11", is_derived: false },
    as_of: "2026-01-06",
    mine: side({ team_id: 1, name: "My Team" }),
    opponent: side({ team_id: 2, name: "Rival Team" }),
    opponent_reason: null,
    comparison: comparison([]),
    schedule_coverage: coverage(),
    streaming: null,
    stale: false,
    synced_at: "2026-01-06T00:00:00Z",
    explanations: null,
    explanations_available: false,
    explanations_reason: null,
    ...overrides,
  };
}

describe("deriveMatchupStats", () => {
  it("(a) week comes straight from the response", () => {
    const result = deriveMatchupStats(matchup({ week: 14 }));
    expect(result.week).toBe(14);
  });

  it("(b) opponent is the other side's name", () => {
    const result = deriveMatchupStats(
      matchup({ opponent: side({ team_id: 9, name: "Boxout Bandits" }) }),
    );
    expect(result.opponent).toBe("Boxout Bandits");
  });

  it("(c) categoriesLed counts only 'winning' verdicts, excluding close, losing, and tied", () => {
    const result = deriveMatchupStats(
      matchup({
        comparison: comparison(
          [
            verdict({ category: "pts", verdict: "winning" }),
            verdict({ category: "reb", verdict: "winning" }),
            verdict({ category: "ast", verdict: "close" }),
            verdict({ category: "stl", verdict: "losing" }),
            verdict({ category: "blk", verdict: "tie" }),
          ],
          { projected_score: [2, 1] },
        ),
      }),
    );
    expect(result.categoriesLed).toBe(2);
  });

  it("(c) categoriesLed is 0 when every category is tied", () => {
    const result = deriveMatchupStats(
      matchup({
        comparison: comparison([
          verdict({ category: "pts", verdict: "tie" }),
          verdict({ category: "reb", verdict: "tie" }),
        ]),
      }),
    );
    expect(result.categoriesLed).toBe(0);
  });

  it("(d) opponent, projected, and categoriesLed are all null when the response has no opponent", () => {
    const result = deriveMatchupStats(matchup({ opponent: null, comparison: null }));
    expect(result.opponent).toBeNull();
    expect(result.projected).toBeNull();
    expect(result.categoriesLed).toBeNull();
    // week is unaffected by the missing opponent
    expect(result.week).toBe(1);
  });

  it("projected and categoriesLed are also null when an opponent is known but the comparison is null (missing schedule coverage)", () => {
    // a real, reachable state: schedule_coverage.ok can be false even with a
    // known opponent, and the backend sends comparison: null in that case
    // (see ScheduleCoverageNotice) -- must not be gated on opponent alone
    const result = deriveMatchupStats(
      matchup({
        opponent: side({ team_id: 3, name: "Rival Team" }),
        comparison: null,
        schedule_coverage: coverage({ ok: false, opponent_games: 0 }),
      }),
    );
    expect(result.opponent).toBe("Rival Team");
    expect(result.projected).toBeNull();
    expect(result.categoriesLed).toBeNull();
  });

  it("projected formats as 'mine-theirs' from the comparison's projected_score", () => {
    const result = deriveMatchupStats(
      matchup({ comparison: comparison([], { projected_score: [6, 3] }) }),
    );
    expect(result.projected).toBe("6-3");
  });
});
