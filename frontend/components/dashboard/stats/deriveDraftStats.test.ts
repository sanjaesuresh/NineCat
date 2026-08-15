import { describe, expect, it } from "vitest";
import { MOCK_DRAFT_TEAMS, pickRound } from "@/components/dashboard/draft/draftSession";
import { deriveDraftStats, type DeriveDraftStatsOptions } from "./deriveDraftStats";

// shared base so each test only overrides the fields it's exercising --
// mirrors the options-object shape deriveDraftStats now takes
const BASE: DeriveDraftStatsOptions = {
  overallPick: 1,
  totalPicks: 72,
  teams: MOCK_DRAFT_TEAMS,
  poolSize: 72,
  appliedPunt: [],
  complete: false,
};

describe("deriveDraftStats", () => {
  it("(a) formats pick as the current overall pick over the total pick count", () => {
    const result = deriveDraftStats({ ...BASE, overallPick: 9 });
    expect(result.pick).toBe("9 of 72");
  });

  it("(b) round matches pickRound's result for the first pick of each of the first three rounds", () => {
    // first pick of round 1, 2, and 3 at the standard 8-team mock draft
    expect(deriveDraftStats({ ...BASE, overallPick: 1 }).round).toBe(
      pickRound(1, MOCK_DRAFT_TEAMS),
    );
    expect(deriveDraftStats({ ...BASE, overallPick: 9 }).round).toBe(
      pickRound(9, MOCK_DRAFT_TEAMS),
    );
    expect(deriveDraftStats({ ...BASE, overallPick: 17 }).round).toBe(
      pickRound(17, MOCK_DRAFT_TEAMS),
    );
    // pin the concrete values too, not just equality with pickRound
    expect(deriveDraftStats({ ...BASE, overallPick: 1 }).round).toBe(1);
    expect(deriveDraftStats({ ...BASE, overallPick: 9 }).round).toBe(2);
    expect(deriveDraftStats({ ...BASE, overallPick: 17 }).round).toBe(3);
  });

  it("(c) pool returns the draftable pool count passed in", () => {
    expect(deriveDraftStats({ ...BASE, poolSize: 54 }).pool).toBe(54);
    expect(deriveDraftStats({ ...BASE, poolSize: 0 }).pool).toBe(0);
  });

  it("(d) puntLabels is empty when no punt is applied, and translated display labels otherwise", () => {
    expect(deriveDraftStats({ ...BASE, appliedPunt: [] }).puntLabels).toEqual([]);
    expect(
      deriveDraftStats({ ...BASE, appliedPunt: ["reb", "blk"] }).puntLabels,
    ).toEqual(["REB", "BLK"]);
  });

  it("(e) pick and round are null once the draft is complete, since overallPick overshoots totalPicks by design (useDraftSession's draftComplete check) rather than clamping at it", () => {
    // 9-round, 8-team draft: overallPick lands at 73 once the last pick (72) is made
    const result = deriveDraftStats({ ...BASE, overallPick: 73, complete: true });
    expect(result.pick).toBeNull();
    expect(result.round).toBeNull();
    // pool and puntLabels are unaffected by completion
    expect(result.pool).toBe(72);
  });

  it("(f) puntLabels is a fresh array, not the caller's appliedPunt reference, so mutating it can't corrupt caller state", () => {
    const punt = ["reb"];
    const result = deriveDraftStats({ ...BASE, appliedPunt: punt });
    expect(result.puntLabels).not.toBe(punt);
  });
});
