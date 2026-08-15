import { describe, expect, it } from "vitest";
import type {
  AddsCandidate,
  LeagueAddsResponse,
  LeagueTradesResponse,
  TradeSide,
  TradeSideOutcome,
  TradeVerdict,
} from "@/lib/api";
import { deriveAddsStats, deriveTradesStats } from "./deriveListStats";

// minimal fillers -- every field is required on the wire, so tests spell it
// out explicitly rather than relying on partial defaults, matching
// deriveMatchupStats.test.ts's builder convention

function candidate(overrides: Partial<AddsCandidate> & { player_key: string }): AddsCandidate {
  return {
    name: "Player",
    position: null,
    nba_person_id: 1,
    headshot_url: null,
    score: 1,
    games_remaining: 3,
    categories_helped: [],
    stat_basis: "projection",
    reasons: [],
    ...overrides,
  };
}

function adds(overrides: Partial<LeagueAddsResponse> = {}): LeagueAddsResponse {
  return {
    week: 1,
    week_range: { start_date: "2026-01-05", end_date: "2026-01-11", is_derived: false },
    as_of: "2026-01-06",
    window_basis: "remaining",
    close_categories: [],
    opponent_reason: null,
    candidates: [],
    schedule_coverage: { mine_games: 7, opponent_games: 7, ok: true },
    stale: false,
    synced_at: "2026-01-06T00:00:00Z",
    explanations: null,
    explanations_available: false,
    explanations_reason: null,
    ...overrides,
  };
}

function outcome(overrides: Partial<TradeSideOutcome> = {}): TradeSideOutcome {
  return {
    before: { totals: {}, labels: {}, means: {} },
    after: { totals: {}, labels: {}, means: {} },
    gained: [],
    lost: [],
    collapsed: [],
    ...overrides,
  };
}

function verdict(overrides: Partial<TradeVerdict> & { verdict: string }): TradeVerdict {
  return {
    give: ["p1"],
    get: ["p2"],
    mine: outcome(),
    theirs: outcome(),
    net_value: 0,
    reasons: [],
    ...overrides,
  };
}

function side(overrides: Partial<TradeSide> & { team_id: number }): TradeSide {
  return {
    categories: {},
    surplus: [],
    deficit: [],
    ...overrides,
  };
}

function trades(overrides: Partial<LeagueTradesResponse> = {}): LeagueTradesResponse {
  return {
    mine: side({ team_id: 1 }),
    theirs: side({ team_id: 2 }),
    players: {},
    verdicts: [],
    evaluated: 0,
    truncated: false,
    value_basis: "category_impact_only",
    stale: false,
    synced_at: "2026-01-06T00:00:00Z",
    explanations: null,
    explanations_available: false,
    explanations_reason: null,
    ...overrides,
  };
}

describe("deriveAddsStats", () => {
  it("(a) candidates counts the returned candidate rows", () => {
    const result = deriveAddsStats(
      adds({
        candidates: [
          candidate({ player_key: "a" }),
          candidate({ player_key: "b" }),
          candidate({ player_key: "c" }),
        ],
      }),
    );
    expect(result.candidates).toBe(3);
  });

  it("(a) candidates is 0 for an empty candidate list", () => {
    const result = deriveAddsStats(adds({ candidates: [] }));
    expect(result.candidates).toBe(0);
  });
});

describe("deriveTradesStats", () => {
  it("(c) proposals counts the returned trade verdicts", () => {
    const result = deriveTradesStats(
      trades({
        verdicts: [
          verdict({ verdict: "favors_me" }),
          verdict({ verdict: "balanced" }),
        ],
      }),
    );
    expect(result.proposals).toBe(2);
  });

  it("(d) bestVerdict is null for an empty proposal list", () => {
    const result = deriveTradesStats(trades({ verdicts: [] }));
    expect(result.proposals).toBe(0);
    expect(result.bestVerdict).toBeNull();
  });

  it("(e) bestVerdict returns the label of the highest-ranked (first) proposal for a non-empty list", () => {
    const result = deriveTradesStats(
      trades({
        verdicts: [
          verdict({ verdict: "favors_me" }),
          verdict({ verdict: "rejected" }),
        ],
      }),
    );
    expect(result.bestVerdict).toBe("Favors you");
  });

  it("(e) bestVerdict returns the FIRST proposal's label even when a later one ranks 'better' -- pins that this takes the top-ranked proposal, not the best verdict", () => {
    // reversed relative to the case above: here the first element is the
    // WORSE verdict ("rejected") and a later element is the "better" one
    // ("favors_me"). An implementation that picked the best verdict across
    // the list rather than verdicts[0] would pass the earlier test
    // identically but fail this one.
    const result = deriveTradesStats(
      trades({
        verdicts: [
          verdict({ verdict: "rejected" }),
          verdict({ verdict: "favors_me" }),
        ],
      }),
    );
    expect(result.bestVerdict).toBe("Not worth it");
  });

  it("(e) bestVerdict covers all four known verdict labels", () => {
    expect(deriveTradesStats(trades({ verdicts: [verdict({ verdict: "favors_me" })] })).bestVerdict).toBe(
      "Favors you",
    );
    expect(
      deriveTradesStats(trades({ verdicts: [verdict({ verdict: "favors_them" })] })).bestVerdict,
    ).toBe("Favors them");
    expect(
      deriveTradesStats(trades({ verdicts: [verdict({ verdict: "balanced" })] })).bestVerdict,
    ).toBe("Balanced");
    expect(
      deriveTradesStats(trades({ verdicts: [verdict({ verdict: "rejected" })] })).bestVerdict,
    ).toBe("Not worth it");
  });

  it("bestVerdict surfaces an unrecognized verdict explicitly rather than silently mislabeling it", () => {
    const result = deriveTradesStats(trades({ verdicts: [verdict({ verdict: "mystery" })] }));
    expect(result.bestVerdict).toBe("Unrecognized verdict (mystery)");
  });
});
