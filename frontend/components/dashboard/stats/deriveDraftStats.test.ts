import { describe, expect, it } from "vitest";
import { MOCK_DRAFT_TEAMS, pickRound } from "@/components/dashboard/draft/draftSession";
import { deriveDraftStats } from "./deriveDraftStats";

describe("deriveDraftStats", () => {
  it("(a) formats pick as the current overall pick over the total pick count", () => {
    const result = deriveDraftStats(9, 72, MOCK_DRAFT_TEAMS, 72, [], false);
    expect(result.pick).toBe("9 of 72");
  });

  it("(b) round matches pickRound's result for the first pick of each of the first three rounds", () => {
    // first pick of round 1, 2, and 3 at the standard 8-team mock draft
    expect(deriveDraftStats(1, 72, MOCK_DRAFT_TEAMS, 72, [], false).round).toBe(
      pickRound(1, MOCK_DRAFT_TEAMS),
    );
    expect(deriveDraftStats(9, 72, MOCK_DRAFT_TEAMS, 72, [], false).round).toBe(
      pickRound(9, MOCK_DRAFT_TEAMS),
    );
    expect(deriveDraftStats(17, 72, MOCK_DRAFT_TEAMS, 72, [], false).round).toBe(
      pickRound(17, MOCK_DRAFT_TEAMS),
    );
    // pin the concrete values too, not just equality with pickRound
    expect(deriveDraftStats(1, 72, MOCK_DRAFT_TEAMS, 72, [], false).round).toBe(1);
    expect(deriveDraftStats(9, 72, MOCK_DRAFT_TEAMS, 72, [], false).round).toBe(2);
    expect(deriveDraftStats(17, 72, MOCK_DRAFT_TEAMS, 72, [], false).round).toBe(3);
  });

  it("(c) pool returns the draftable pool count passed in", () => {
    expect(deriveDraftStats(1, 72, MOCK_DRAFT_TEAMS, 54, [], false).pool).toBe(54);
    expect(deriveDraftStats(1, 72, MOCK_DRAFT_TEAMS, 0, [], false).pool).toBe(0);
  });

  it("(d) puntLabels is empty when no punt is applied, and translated display labels otherwise", () => {
    expect(deriveDraftStats(1, 72, MOCK_DRAFT_TEAMS, 72, [], false).puntLabels).toEqual([]);
    expect(
      deriveDraftStats(1, 72, MOCK_DRAFT_TEAMS, 72, ["reb", "blk"], false).puntLabels,
    ).toEqual(["REB", "BLK"]);
  });

  it("(e) pick and round are null once the draft is complete, since overallPick overshoots totalPicks by design (useDraftSession's draftComplete check) rather than clamping at it", () => {
    // 9-round, 8-team draft: overallPick lands at 73 once the last pick (72) is made
    const result = deriveDraftStats(73, 72, MOCK_DRAFT_TEAMS, 72, [], true);
    expect(result.pick).toBeNull();
    expect(result.round).toBeNull();
    // pool and puntLabels are unaffected by completion
    expect(result.pool).toBe(72);
  });

  it("(f) puntLabels is a fresh array, not the caller's appliedPunt reference, so mutating it can't corrupt caller state", () => {
    const punt = ["reb"];
    const result = deriveDraftStats(1, 72, MOCK_DRAFT_TEAMS, 72, punt, false);
    expect(result.puntLabels).not.toBe(punt);
  });
});
