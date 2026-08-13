import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  MAY_NOT_LAST_REASON,
  MOCK_DRAFT_TEAMS,
  mockDraftRounds,
  mulberry32,
  pickRound,
  snakeTeamForPick,
  weightedAdpPick,
} from "./draftSession";

describe("mockDraftRounds", () => {
  it("derives 9 rounds from the seeded 72-player pool at 8 teams", () => {
    expect(mockDraftRounds(72)).toBe(9);
  });

  it("shrinks below the 9-round default when the pool is smaller", () => {
    expect(mockDraftRounds(40)).toBe(5); // floor(40/8)
  });

  it("never exceeds 9 rounds even for an oversized pool", () => {
    expect(mockDraftRounds(400)).toBe(9);
  });

  it("returns 0 when the pool can't fill even one round", () => {
    expect(mockDraftRounds(5)).toBe(0);
  });
});

describe("snakeTeamForPick", () => {
  it("goes forward in odd rounds", () => {
    expect(snakeTeamForPick(1, 8)).toBe(1);
    expect(snakeTeamForPick(8, 8)).toBe(8);
  });

  it("reverses in even rounds", () => {
    expect(snakeTeamForPick(9, 8)).toBe(8); // round 2, pick 1 -> team 8
    expect(snakeTeamForPick(16, 8)).toBe(1); // round 2, pick 8 -> team 1
  });

  it("matches the backend's picks_until_next_turn derivation for team 1", () => {
    // team 1 picks at overall 1, then 16 (round 2 reversed), then 17 (round 3)
    expect(snakeTeamForPick(1, 8)).toBe(1);
    expect(snakeTeamForPick(16, 8)).toBe(1);
    expect(snakeTeamForPick(17, 8)).toBe(1);
  });
});

describe("pickRound", () => {
  it("computes the 1-based round for a pick number", () => {
    expect(pickRound(1, MOCK_DRAFT_TEAMS)).toBe(1);
    expect(pickRound(8, MOCK_DRAFT_TEAMS)).toBe(1);
    expect(pickRound(9, MOCK_DRAFT_TEAMS)).toBe(2);
    expect(pickRound(72, MOCK_DRAFT_TEAMS)).toBe(9);
  });
});

describe("mulberry32", () => {
  it("is deterministic: the same seed produces the same sequence", () => {
    const a = mulberry32(42);
    const b = mulberry32(42);
    const seqA = [a(), a(), a()];
    const seqB = [b(), b(), b()];
    expect(seqA).toEqual(seqB);
  });

  it("different seeds diverge (not a constant function)", () => {
    const a = mulberry32(1)();
    const b = mulberry32(2)();
    expect(a).not.toBe(b);
  });

  it("always returns a value in [0, 1)", () => {
    const rng = mulberry32(7);
    for (let i = 0; i < 50; i++) {
      const v = rng();
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });
});

describe("weightedAdpPick", () => {
  it("returns null for an empty candidate list", () => {
    expect(weightedAdpPick([], mulberry32(1))).toBeNull();
  });

  it("only ever returns a candidate that was in the list", () => {
    const candidates = ["a", "b", "c", "d", "e", "f"];
    const rng = mulberry32(99);
    for (let i = 0; i < 30; i++) {
      const pick = weightedAdpPick(candidates, rng);
      expect(candidates).toContain(pick);
    }
  });

  it("is reproducible given the same seeded rng sequence", () => {
    const candidates = ["a", "b", "c", "d", "e"];
    const picksA = Array.from({ length: 10 }, () =>
      weightedAdpPick(candidates, mulberry32(555)),
    );
    // fresh rng per call above (deliberately re-seeded each time) means every
    // entry equals the FIRST draw for that seed -- this pins that a fixed
    // seed always yields the same first pick, the property Reset relies on
    expect(new Set(picksA).size).toBe(1);
  });

  it("heavily favors the top of the list over many draws (weights [8,4,2,1,1])", () => {
    const candidates = ["top", "b", "c", "d", "e"];
    const rng = mulberry32(2026);
    let topCount = 0;
    const draws = 2000;
    for (let i = 0; i < draws; i++) {
      if (weightedAdpPick(candidates, rng) === "top") topCount++;
    }
    // expected ~8/16 = 50% -- assert a generous band so this isn't flaky
    expect(topCount / draws).toBeGreaterThan(0.35);
    expect(topCount / draws).toBeLessThan(0.65);
  });
});

describe("MAY_NOT_LAST_REASON", () => {
  it("matches the exact reason string engine/draft_sim.py's _reasons() emits", () => {
    // reads the backend source directly rather than trusting the two files
    // to stay in sync by convention -- if the backend rewords this reason,
    // this test fails immediately instead of the frontend's de-emphasis
    // logic silently going inert (a card-per-row "may not last" badge would
    // quietly return on a thin pool, the exact regression T4 fixed)
    const backendPath = path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      "../../../../backend/src/ninecat/engine/draft_sim.py",
    );
    const src = readFileSync(backendPath, "utf-8");
    expect(src).toContain(`"${MAY_NOT_LAST_REASON}"`);
  });
});
