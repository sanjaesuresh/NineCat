// pure 9-cat draft/trade math, ported one-to-one from the working <script> block in
// frontend/public/mockups/d-retrodata.html — no behavior changes, just typed and testable.
import { POOL, type PlayerRow } from "./hashtagPool";

export type Cat =
  | "pts"
  | "reb"
  | "ast"
  | "stl"
  | "blk"
  | "tpm"
  | "fgp"
  | "ftp"
  | "to";

export interface CatInfo {
  readonly key: Cat;
  readonly label: string;
}

// fixed order drives table columns, ticker rows, and swing-grid layout downstream
export const CATS: readonly CatInfo[] = [
  { key: "pts", label: "Pts" },
  { key: "reb", label: "Reb" },
  { key: "ast", label: "Ast" },
  { key: "stl", label: "Stl" },
  { key: "blk", label: "Blk" },
  { key: "tpm", label: "3pm" },
  { key: "fgp", label: "Fg%" },
  { key: "ftp", label: "Ft%" },
  { key: "to", label: "To" },
];

const CAT_KEYS: readonly Cat[] = CATS.map((c) => c.key);

// raw counting-stat accessor used both for z-score inputs (non-pct cats) and for the
// trade ledger's plain per-game display delta
function statValue(p: PlayerRow, cat: Cat): number {
  switch (cat) {
    case "pts":
      return p.points;
    case "reb":
      return p.rebounds;
    case "ast":
      return p.assists;
    case "stl":
      return p.steals;
    case "blk":
      return p.blocks;
    case "tpm":
      return p.threes;
    case "fgp":
      return p.fieldGoalPct;
    case "ftp":
      return p.freeThrowPct;
    case "to":
      return p.turnovers;
  }
}

// league-wide attempt-weighted fg%/ft% baselines — a simple average of percentages would
// let a low-volume small-sample shooter swing the baseline as much as a high-volume starter
// exported so tests can pin the exact value: swapping this for an unweighted mean silently
// changes which player gets drafted under several punt combinations
export const LG_FG =
  POOL.reduce((s, p) => s + p.fieldGoalPct * p.fieldGoalAttempts, 0) /
  POOL.reduce((s, p) => s + p.fieldGoalAttempts, 0);
export const LG_FT =
  POOL.reduce((s, p) => s + p.freeThrowPct * p.freeThrowAttempts, 0) /
  POOL.reduce((s, p) => s + p.freeThrowAttempts, 0);

// the value fed into the z-score: percentage cats are volume-weighted (pct above/below
// league baseline, scaled by attempts) so a .70 ft% on 10 attempts counts more than on 2;
// every other cat is just the raw per-game counting stat
function rawZInput(p: PlayerRow, cat: Cat): number {
  if (cat === "fgp") return (p.fieldGoalPct - LG_FG) * p.fieldGoalAttempts;
  if (cat === "ftp") return (p.freeThrowPct - LG_FT) * p.freeThrowAttempts;
  return statValue(p, cat);
}

// pool-wide mean/stddev per category, computed once at module load — every zScore()
// call reuses these fixed baselines instead of recomputing over the whole pool
const MU: Record<Cat, number> = {} as Record<Cat, number>;
const SD: Record<Cat, number> = {} as Record<Cat, number>;
for (const cat of CAT_KEYS) {
  const values = POOL.map((p) => rawZInput(p, cat));
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance =
    values.reduce((a, b) => a + (b - mean) * (b - mean), 0) / values.length;
  MU[cat] = mean;
  // fall back to 1 for a zero-variance category so division never produces NaN/Infinity
  SD[cat] = Math.sqrt(variance) || 1;
}

/** volume-weighted z-score for one player/category; turnovers are negated so higher is always better. */
export function zScore(player: PlayerRow, cat: Cat): number {
  const s = (rawZInput(player, cat) - MU[cat]) / SD[cat];
  return cat === "to" ? -s : s;
}

/** sum of z across every category except the punted ones — the draft-pick value function. */
export function puntValue(player: PlayerRow, punts: readonly Cat[]): number {
  return CAT_KEYS.reduce(
    (sum, cat) => (punts.includes(cat) ? sum : sum + zScore(player, cat)),
    0,
  );
}

export interface DraftPick {
  readonly player: PlayerRow;
  readonly overall: number;
}

// 12-team snake draft from slot 4: each round alternates direction, so my slot lands
// on overall picks 4, 21, 28, 45, 52 across the five rounds.
const MY_PICKS: readonly number[] = [4, 21, 28, 45, 52];

/**
 * Simulates a 12-team snake draft. Every other team takes the next-best player strictly
 * by Hashtag rank; on my five picks I take whichever remaining player maximizes
 * puntValue() under the given punts. Returns my five picks in draft order.
 */
export function snakeDraft(punts: readonly Cat[]): readonly DraftPick[] {
  // a 52-pick draft needs at least 52 players on the board; without this guard, splicing
  // an exhausted array silently yields `undefined` and TypeScript can't catch it
  if (POOL.length < 52) {
    throw new Error(
      `snakeDraft: pool has ${POOL.length} players, need at least 52 for a 52-pick draft`,
    );
  }

  // copy before sorting — POOL is readonly and Array.sort mutates in place
  const avail = [...POOL].sort((a, b) => a.rank - b.rank);
  const mine: DraftPick[] = [];

  for (let pick = 1; pick <= 52; pick++) {
    if (MY_PICKS.includes(pick)) {
      let bestIndex = 0;
      for (let i = 1; i < avail.length; i++) {
        if (puntValue(avail[i], punts) > puntValue(avail[bestIndex], punts)) {
          bestIndex = i;
        }
      }
      const [player] = avail.splice(bestIndex, 1);
      mine.push({ player, overall: pick });
    } else {
      // other teams draft straight off the board — avail is rank-sorted, so shift()
      // always removes the best remaining player by rank
      avail.shift();
    }
  }

  return mine;
}

/** Formats an overall pick number as "round.pick", e.g. 21 -> "2.09" (12-team league). */
export function pickLabel(overall: number): string {
  const round = Math.ceil(overall / 12);
  const slot = overall - (round - 1) * 12;
  return `${round}.${String(slot).padStart(2, "0")}`;
}

/** Per-category z-score sum across a roster (higher is always better, turnovers included). */
export function rosterStrength(
  roster: readonly PlayerRow[],
): Record<Cat, number> {
  const out: Record<Cat, number> = {} as Record<Cat, number>;
  for (const cat of CAT_KEYS) {
    out[cat] = roster.reduce((sum, p) => sum + zScore(p, cat), 0);
  }
  return out;
}

function findPlayer(name: string): PlayerRow {
  const found = POOL.find((p) => p.name === name);
  if (!found) {
    throw new Error(`puntDraft: unknown player "${name}"`);
  }
  return found;
}

export type SwingClassification = "gain" | "concede" | "push";

export interface TradeSwingCategory {
  readonly cat: Cat;
  readonly label: string;
  /** raw per-game delta (receive - send), unweighted — what the ledger displays. */
  readonly rawDelta: number;
  /** z-score delta (receive - send), volume-weighted and turnover-inverted. */
  readonly zDelta: number;
  readonly classification: SwingClassification;
}

export interface TradeSwingResult {
  readonly categories: readonly TradeSwingCategory[];
  readonly gain: number;
  readonly concede: number;
  readonly push: number;
}

// z-delta magnitudes below this are a wash — not worth counting as a real category swing
const SWING_THRESHOLD = 0.25;

/** Per-category trade impact of sending `sendName` and receiving `receiveName`. */
export function tradeSwing(sendName: string, receiveName: string): TradeSwingResult {
  const send = findPlayer(sendName);
  const receive = findPlayer(receiveName);

  let gain = 0;
  let concede = 0;
  let push = 0;

  const categories: TradeSwingCategory[] = CATS.map(({ key, label }) => {
    // volume-weighted, turnover-inverted — the number that decides good/bad for you
    const zDelta = zScore(receive, key) - zScore(send, key);
    // plain per-game difference — what gets printed in the ledger regardless of sign meaning
    const rawDelta = statValue(receive, key) - statValue(send, key);

    let classification: SwingClassification;
    if (zDelta > SWING_THRESHOLD) {
      classification = "gain";
      gain++;
    } else if (zDelta < -SWING_THRESHOLD) {
      classification = "concede";
      concede++;
    } else {
      classification = "push";
      push++;
    }

    return { cat: key, label, rawDelta, zDelta, classification };
  });

  return { categories, gain, concede, push };
}
