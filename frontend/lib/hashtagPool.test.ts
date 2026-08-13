import { describe, expect, it } from "vitest";
import { POOL, SOURCE_NAME, SOURCE_SEASON, SOURCE_URL } from "./hashtagPool";

// deterministic djb2-style string hash — used to pin the exact serialized contents of
// POOL so any single-field corruption (swap, digit transposition, typo) fails a test
// even if it doesn't change length, rank order, or column sums
function hashString(input: string): number {
  let hash = 5381;
  for (let i = 0; i < input.length; i++) {
    hash = (hash * 33) ^ input.charCodeAt(i);
  }
  return hash >>> 0;
}

describe("hashtagPool", () => {
  it("has 59 entries (ranks 1-60, rank 52 intentionally excluded)", () => {
    expect(POOL).toHaveLength(59);
  });

  it("ranks strictly ascend", () => {
    for (let i = 1; i < POOL.length; i++) {
      expect(POOL[i].rank).toBeGreaterThan(POOL[i - 1].rank);
    }
  });

  it("excludes rank 52 and has rank 1 as Nikola Jokic", () => {
    expect(POOL.some((p) => p.rank === 52)).toBe(false);
    expect(POOL[0].rank).toBe(1);
    expect(POOL[0].name).toBe("Nikola Jokic");
  });

  it("every row has percentages as fractions, non-negative attempts, and non-empty identity fields", () => {
    for (const p of POOL) {
      expect(p.fieldGoalPct).toBeGreaterThan(0);
      expect(p.fieldGoalPct).toBeLessThan(1);
      expect(p.freeThrowPct).toBeGreaterThan(0);
      expect(p.freeThrowPct).toBeLessThan(1);
      expect(p.fieldGoalAttempts).toBeGreaterThanOrEqual(0);
      expect(p.freeThrowAttempts).toBeGreaterThanOrEqual(0);
      expect(p.name.length).toBeGreaterThan(0);
      expect(p.position.length).toBeGreaterThan(0);
      expect(p.team.length).toBeGreaterThan(0);
    }
  });

  it("player names are unique (a swapped-in duplicate row would not otherwise be caught)", () => {
    const names = POOL.map((p) => p.name);
    expect(new Set(names).size).toBe(names.length);
  });

  // z-scores downstream are computed from pool-wide means/stddevs, so a single corrupted
  // value (a digit transposition, a swapped stat pair) shifts the baseline for every
  // player, not just the row it's in — pin per-column sums so that class of bug fails here
  it("per-column numeric sums match the verified totals", () => {
    const sum = (key: keyof (typeof POOL)[number]) =>
      POOL.reduce((total, p) => total + (p[key] as number), 0);

    expect(sum("points")).toBeCloseTo(1269.1, 6);
    expect(sum("rebounds")).toBeCloseTo(403.7, 6);
    expect(sum("assists")).toBeCloseTo(289.6, 6);
    expect(sum("steals")).toBeCloseTo(68.9, 6);
    expect(sum("blocks")).toBeCloseTo(47.1, 6);
    expect(sum("threes")).toBeCloseTo(118.3, 6);
    expect(sum("fieldGoalPct")).toBeCloseTo(29.252, 3);
    expect(sum("fieldGoalAttempts")).toBeCloseTo(917.7, 6);
    expect(sum("freeThrowPct")).toBeCloseTo(48.235, 3);
    expect(sum("freeThrowAttempts")).toBeCloseTo(307.9, 6);
    expect(sum("turnovers")).toBeCloseTo(148.5, 6);
  });

  // catches corruptions that per-column sums can miss (e.g. a value moved between two
  // rows in the same column nets to the same sum) by hashing the full serialized pool
  it("serialized pool matches the verified checksum", () => {
    expect(hashString(JSON.stringify(POOL))).toBe(3914737772);
  });

  // boundary rows: rank 1 is the first row, ranks 51/53 bracket the intentional
  // rank-52 gap (where an off-by-one splice would land), rank 60 is the last row
  it("boundary rows match field-by-field", () => {
    const byRank = (rank: number) => POOL.find((p) => p.rank === rank);

    expect(byRank(1)).toEqual({
      rank: 1,
      name: "Nikola Jokic",
      position: "C",
      team: "DEN",
      points: 27.7,
      rebounds: 12.9,
      assists: 10.7,
      steals: 1.4,
      blocks: 0.8,
      threes: 1.7,
      fieldGoalPct: 0.569,
      fieldGoalAttempts: 17.4,
      freeThrowPct: 0.831,
      freeThrowAttempts: 7.4,
      turnovers: 3.7,
    });

    expect(byRank(51)).toEqual({
      rank: 51,
      name: "Brandon Miller",
      position: "SF",
      team: "CHA",
      points: 20.2,
      rebounds: 4.9,
      assists: 3.3,
      steals: 1.0,
      blocks: 0.7,
      threes: 3.1,
      fieldGoalPct: 0.435,
      fieldGoalAttempts: 16.1,
      freeThrowPct: 0.892,
      freeThrowAttempts: 3.4,
      turnovers: 2.5,
    });

    expect(byRank(53)).toEqual({
      rank: 53,
      name: "Ryan Rollins",
      position: "PG",
      team: "MIL",
      points: 17.3,
      rebounds: 4.6,
      assists: 5.6,
      steals: 1.5,
      blocks: 0.4,
      threes: 2.5,
      fieldGoalPct: 0.472,
      fieldGoalAttempts: 13.9,
      freeThrowPct: 0.796,
      freeThrowAttempts: 2.1,
      turnovers: 2.7,
    });

    expect(byRank(60)).toEqual({
      rank: 60,
      name: "Rudy Gobert",
      position: "C",
      team: "MIN",
      points: 10.9,
      rebounds: 11.5,
      assists: 1.7,
      steals: 0.8,
      blocks: 1.6,
      threes: 0.0,
      fieldGoalPct: 0.682,
      fieldGoalAttempts: 6.5,
      freeThrowPct: 0.526,
      freeThrowAttempts: 4.0,
      turnovers: 1.4,
    });
  });

  it("attribution constants are pinned exactly (rendered as legally-required attribution copy)", () => {
    expect(SOURCE_NAME).toBe("Hashtag Basketball");
    expect(SOURCE_URL).toBe(
      "https://hashtagbasketball.com/fantasy-basketball-projections"
    );
    // en dash (U+2013), not a hyphen, per the mockup's rendered attribution copy
    expect(SOURCE_SEASON).toBe("2025–26");
  });
});
