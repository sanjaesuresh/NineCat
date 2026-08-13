import { describe, expect, it, vi } from "vitest";
import { POOL, type PlayerRow } from "./hashtagPool";
import {
  CATS,
  LG_FG,
  LG_FT,
  pickLabel,
  puntValue,
  rosterStrength,
  snakeDraft,
  tradeSwing,
  zScore,
  type Cat,
} from "./puntDraft";

// full rank-ordered name list, used to prove immutability without relying only on index 0
const POOL_NAMES_IN_ORDER = POOL.map((p) => p.name);

// builds a synthetic player row so zScore tests can isolate one variable (attempts)
// without depending on which real POOL rows happen to have a given pct/attempt combo
function makePlayer(overrides: Partial<PlayerRow>): PlayerRow {
  return {
    rank: 999,
    name: "Synthetic Player",
    position: "PG",
    team: "ZZZ",
    points: 0,
    rebounds: 0,
    assists: 0,
    steals: 0,
    blocks: 0,
    threes: 0,
    fieldGoalPct: 0.45,
    fieldGoalAttempts: 0,
    freeThrowPct: 0.75,
    freeThrowAttempts: 0,
    turnovers: 0,
    ...overrides,
  };
}

describe("CATS", () => {
  it("lists the nine categories in the mockup's order with matching labels", () => {
    expect(CATS.map((c) => c.key)).toEqual([
      "pts",
      "reb",
      "ast",
      "stl",
      "blk",
      "tpm",
      "fgp",
      "ftp",
      "to",
    ]);
    expect(CATS.map((c) => c.label)).toEqual([
      "Pts",
      "Reb",
      "Ast",
      "Stl",
      "Blk",
      "3pm",
      "Fg%",
      "Ft%",
      "To",
    ]);
  });
});

describe("pickLabel", () => {
  it("formats overall pick 4 as round 1 pick 4", () => {
    expect(pickLabel(4)).toBe("1.04");
  });

  it("formats overall pick 21 as round 2 pick 9", () => {
    expect(pickLabel(21)).toBe("2.09");
  });
});

describe("league baselines", () => {
  // pins the attempt-weighted fg%/ft% baselines exactly — an unweighted mean over the pool
  // is numerically close but silently changes several draft-pick outcomes downstream
  it("computes the attempt-weighted fg% and ft% baselines to reference precision", () => {
    expect(LG_FG).toBeCloseTo(0.48936754930805265, 12);
    expect(LG_FT).toBeCloseTo(0.8190487171159471, 12);
  });
});

describe("zScore", () => {
  // locks the baseline, the population-SD denominator, and the sign convention together:
  // switching to a sample-SD (n-1) denominator changes this value past the 10-decimal bound
  it("computes Nikola Jokic's points z-score to reference precision", () => {
    const jokic = POOL.find((p) => p.name === "Nikola Jokic")!;
    expect(zScore(jokic, "pts")).toBeCloseTo(1.2649714634658675, 10);
  });

  it("treats a high-attempt poor percentage as worse than a low-attempt identical percentage", () => {
    // league fg% baseline is well above 0.30, so a .30 shooter volume-weighted by
    // attempts should score worse the more attempts they take
    const heavyVolume = makePlayer({ fieldGoalPct: 0.3, fieldGoalAttempts: 20 });
    const lightVolume = makePlayer({ fieldGoalPct: 0.3, fieldGoalAttempts: 2 });

    expect(zScore(heavyVolume, "fgp")).toBeLessThan(zScore(lightVolume, "fgp"));
  });

  it("inverts turnovers so fewer turnovers scores higher", () => {
    const fewTos = makePlayer({ turnovers: 1 });
    const manyTos = makePlayer({ turnovers: 5 });

    expect(zScore(fewTos, "to")).toBeGreaterThan(zScore(manyTos, "to"));
  });
});

describe("puntValue", () => {
  it("sums z across categories excluding the punted ones", () => {
    const player = POOL.find((p) => p.name === "Luka Doncic")!;
    const punts: Cat[] = ["ftp", "to"];
    const expected = CATS.filter((c) => !punts.includes(c.key)).reduce(
      (sum, c) => sum + zScore(player, c.key),
      0,
    );

    expect(puntValue(player, punts)).toBeCloseTo(expected, 10);
  });
});

describe("snakeDraft", () => {
  it("does not mutate POOL (copies before sorting)", () => {
    snakeDraft(["ftp", "to"]);
    // checks length + the full ordered name list, not just index 0, so a splice
    // anywhere in the array (not just the front) would be caught
    expect(POOL.length).toBe(59);
    expect(POOL.map((p) => p.name)).toEqual(POOL_NAMES_IN_ORDER);
  });

  it("punting ftp+to drafts Luka Doncic 4, Alperen Sengün 21, Anthony Davis 28", () => {
    const mine = snakeDraft(["ftp", "to"]);

    expect(mine).toHaveLength(5);
    expect(mine.map((m) => m.overall)).toEqual([4, 21, 28, 45, 52]);
    expect(mine[0].player.name).toBe("Luka Doncic");
    expect(mine[1].player.name).toBe("Alperen Sengün");
    expect(mine[2].player.name).toBe("Anthony Davis");
  });

  it("punting ast+fgp drafts Kawhi Leonard at pick 4", () => {
    const mine = snakeDraft(["ast", "fgp"]);

    expect(mine[0].player.name).toBe("Kawhi Leonard");
  });

  // regression guard for the attempt-weighted baseline (H1): under an unweighted-mean
  // baseline this combination drafts Walker Kessler at pick 4 instead of Luka Dončić
  it("punting to+pts drafts Luka Doncic at overall pick 4", () => {
    const mine = snakeDraft(["to", "pts"]);

    expect(mine[0].overall).toBe(4);
    expect(mine[0].player.name).toBe("Luka Doncic");
  });

  it("is deterministic across repeated calls", () => {
    const first = snakeDraft(["ftp", "to"]);
    const second = snakeDraft(["ftp", "to"]);

    expect(second.map((m) => m.player.name)).toEqual(first.map((m) => m.player.name));
    expect(second.map((m) => m.overall)).toEqual(first.map((m) => m.overall));
  });

  it("throws when the pool has fewer than 52 players", async () => {
    vi.resetModules();
    // simulate a future filtered pool (e.g. excluding injured players) dropping below
    // the 52 rows a full draft needs
    vi.doMock("./hashtagPool", async () => {
      const actual = await vi.importActual<typeof import("./hashtagPool")>("./hashtagPool");
      return { ...actual, POOL: actual.POOL.slice(0, 10) };
    });

    const { snakeDraft: draftWithTinyPool } = await import("./puntDraft");
    expect(() => draftWithTinyPool(["ftp", "to"])).toThrow(/52/);

    vi.doUnmock("./hashtagPool");
    vi.resetModules();
  });

  it("re-sorts by rank rather than trusting the incoming pool order", async () => {
    vi.resetModules();
    // the real POOL happens to already be rank-ordered, so this reorders it to prove
    // snakeDraft's own sort — not incidental array order — drives who gets picked
    vi.doMock("./hashtagPool", async () => {
      const actual = await vi.importActual<typeof import("./hashtagPool")>("./hashtagPool");
      return { ...actual, POOL: [...actual.POOL].reverse() };
    });

    const { snakeDraft: draftReversedPool } = await import("./puntDraft");
    const mine = draftReversedPool(["ftp", "to"]);

    // same result as the canonical (already rank-ordered) pool proves the sort ran
    expect(mine.map((m) => m.player.name)).toEqual([
      "Luka Doncic",
      "Alperen Sengün",
      "Anthony Davis",
      "Josh Giddey",
      "Ryan Rollins",
    ]);

    vi.doUnmock("./hashtagPool");
    vi.resetModules();
  });
});

describe("rosterStrength", () => {
  it("sums z per category across a roster", () => {
    const roster = snakeDraft(["ftp", "to"]).map((m) => m.player);
    const strength = rosterStrength(roster);

    for (const c of CATS) {
      const expected = roster.reduce((sum, p) => sum + zScore(p, c.key), 0);
      expect(strength[c.key]).toBeCloseTo(expected, 10);
    }
  });
});

describe("tradeSwing", () => {
  it("Cade Cunningham for Lauri Markkanen: gain 6, concede 3, push 0", () => {
    const result = tradeSwing("Cade Cunningham", "Lauri Markkanen");

    expect(result.gain).toBe(6);
    expect(result.concede).toBe(3);
    expect(result.push).toBe(0);
  });

  it("classifies the turnover column as a gain even though the raw delta is negative", () => {
    const result = tradeSwing("Cade Cunningham", "Lauri Markkanen");
    const toCat = result.categories.find((c) => c.cat === "to")!;

    expect(toCat.rawDelta).toBeLessThan(0);
    expect(toCat.classification).toBe("gain");
  });

  it("throws on an unknown player name", () => {
    expect(() => tradeSwing("Nobody Real", "Lauri Markkanen")).toThrow();
  });

  // exercises the push branch with a real player pair (never hit by the other trade
  // tests) and pins a zDelta that lands strictly between 0.05 and 0.25 — this also
  // catches SWING_THRESHOLD being loosened to 0.05, which would misclassify it as a gain
  it("Nikola Jokic for Victor Wembanyama: classifies tpm as a push and counts it", () => {
    const result = tradeSwing("Nikola Jokic", "Victor Wembanyama");
    const tpmCat = result.categories.find((c) => c.cat === "tpm")!;

    expect(tpmCat.zDelta).toBeGreaterThan(0.05);
    expect(tpmCat.zDelta).toBeLessThan(0.25);
    expect(tpmCat.classification).toBe("push");

    expect(result.gain).toBe(2);
    expect(result.concede).toBe(5);
    expect(result.push).toBe(2);
  });
});
