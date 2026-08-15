import { describe, expect, it } from "vitest";
import type { LeagueOverviewResponse, LeagueTeamResponse, StandingsEntry } from "@/lib/api";
import { deriveTeamStats } from "./deriveTeamStats";

// minimal StandingsEntry builder -- every field is required on the wire, so
// tests spell it out explicitly rather than relying on partial defaults
function standingsRow(overrides: Partial<StandingsEntry> & { team_id: number }): StandingsEntry {
  return {
    name: `Team ${overrides.team_id}`,
    rank: 1,
    wins: 0,
    losses: 0,
    ties: 0,
    ...overrides,
  };
}

function overview(overrides: Partial<LeagueOverviewResponse> = {}): LeagueOverviewResponse {
  return {
    standings: [standingsRow({ team_id: 1, rank: 1, wins: 10, losses: 4, ties: 1 })],
    my_team_id: 1,
    matchup: null,
    stale: false,
    synced_at: "2026-08-14T00:00:00Z",
    ...overrides,
  };
}

// loosened to `unknown` (rather than `number`) so tests can construct a
// non-numeric mean entry -- the derivation's filter/guard has to handle a
// value that isn't a number, which a `Record<string, number>` param can't
// express at the call site
function team(
  means: Record<string, unknown> = {},
  labels: Record<string, unknown> = {},
): LeagueTeamResponse {
  return {
    roster: [],
    build_profile: { totals: {}, labels, means },
    stale: false,
    synced_at: "2026-08-14T00:00:00Z",
  };
}

describe("deriveTeamStats", () => {
  it("(a) formats record from the caller's own standings row, matched by my_team_id", () => {
    const ov = overview({
      my_team_id: 7,
      standings: [
        standingsRow({ team_id: 3, wins: 1, losses: 9, ties: 0 }),
        standingsRow({ team_id: 7, wins: 8, losses: 5, ties: 2 }),
      ],
    });
    const result = deriveTeamStats(ov, team());
    expect(result.record).toBe("8-5-2");
  });

  it("(b) renders rank as the row's rank over the total number of standings rows", () => {
    const ov = overview({
      my_team_id: 7,
      standings: [
        standingsRow({ team_id: 3, rank: 1 }),
        standingsRow({ team_id: 7, rank: 2 }),
        standingsRow({ team_id: 9, rank: 3 }),
      ],
    });
    const result = deriveTeamStats(ov, team());
    expect(result.rank).toBe("2/3");
  });

  it("(c) strongest/weakest are gated by the backend's own strong/punt labels, most extreme first", () => {
    const result = deriveTeamStats(
      overview(),
      team(
        {
          pts: 1.2,
          reb: -0.8,
          ast: 0.5,
          stl: 2.1,
          blk: -1.9,
          tpm: 0.1,
          fg_pct: -0.3,
          // highest mean in the payload after stl/pts, but labelled "average"
          // (not "strong") by the backend -- must NOT appear in strongest,
          // proving the gate is the label, not the raw number
          ft_pct: 0.9,
          tov: -0.2,
        },
        {
          pts: "strong",
          reb: "punt",
          ast: "average",
          stl: "strong",
          blk: "punt",
          tpm: "average",
          fg_pct: "average",
          ft_pct: "average",
          tov: "average",
        },
      ),
    );
    // strongest: highest mean first among "strong"-labelled categories
    expect(result.strongest).toEqual(["stl", "pts"]);
    // weakest: worst (lowest) mean first among "punt"-labelled categories --
    // this also pins the ordering fix (previously blk read second)
    expect(result.weakest).toEqual(["blk", "reb"]);
  });

  it("(d) record and rank are null (not thrown) when my_team_id is null", () => {
    const ov = overview({
      my_team_id: null,
      standings: [standingsRow({ team_id: 1, rank: 1, wins: 10, losses: 4, ties: 1 })],
    });
    expect(() => deriveTeamStats(ov, team())).not.toThrow();
    const result = deriveTeamStats(ov, team());
    expect(result.record).toBeNull();
    expect(result.rank).toBeNull();
  });

  it("(e) two-category boundary: both strong-labelled categories land in strongest, weakest stays empty", () => {
    // exactly two categories in the payload, both labelled "strong" -- pins
    // the corrected, label-gated behavior (the old naive top-two/bottom-two
    // split would have put one of these in weakest purely by position)
    const result = deriveTeamStats(
      overview(),
      team({ pts: 1.0, reb: 0.5 }, { pts: "strong", reb: "strong" }),
    );
    expect(result.strongest).toEqual(["pts", "reb"]);
    expect(result.weakest).toEqual([]);
  });

  it("filters a non-numeric mean entry instead of crashing or ranking it", () => {
    // `means` is a loose Record<string, unknown> on the wire; a malformed or
    // missing value for one category must not blow up the sort or sneak into
    // either list even when its label claims "strong"
    const result = deriveTeamStats(
      overview(),
      team(
        { pts: 1.0, reb: null, ast: -0.9 },
        { pts: "strong", reb: "strong", ast: "punt" },
      ),
    );
    expect(result.strongest).toEqual(["pts"]);
    expect(result.weakest).toEqual(["ast"]);
  });

  it("an all-'average', all-zero build profile (no roster player mapped) yields no strongest/weakest", () => {
    // the backend emits 0.0 for every category with an "average" label when
    // no roster player maps to an NBA player id -- neither list may assert
    // a confident pick out of an undifferentiated, unclassified payload
    const result = deriveTeamStats(
      overview(),
      team(
        { pts: 0, reb: 0, ast: 0, stl: 0, blk: 0, tpm: 0, fg_pct: 0, ft_pct: 0, tov: 0 },
        {
          pts: "average",
          reb: "average",
          ast: "average",
          stl: "average",
          blk: "average",
          tpm: "average",
          fg_pct: "average",
          ft_pct: "average",
          tov: "average",
        },
      ),
    );
    expect(result.strongest).toEqual([]);
    expect(result.weakest).toEqual([]);
  });

  it("record/rank are null when my_team_id doesn't match any standings row", () => {
    const ov = overview({
      my_team_id: 99,
      standings: [standingsRow({ team_id: 1, rank: 1, wins: 10, losses: 4, ties: 1 })],
    });
    const result = deriveTeamStats(ov, team());
    expect(result.record).toBeNull();
    expect(result.rank).toBeNull();
  });

  it("strongest and weakest are both empty for an empty build profile", () => {
    const result = deriveTeamStats(overview(), team({}));
    expect(result.strongest).toEqual([]);
    expect(result.weakest).toEqual([]);
  });
});
