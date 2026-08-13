// Pure, framework-free helpers for the client-side mock draft. The backend's
// snake-order simulator (engine/draft_sim.py) is never called from the
// browser (D7 — opponent picks run client-side off the board's ADP order to
// avoid a chatty endpoint), so this file re-derives just the small amount of
// snake-draft arithmetic the UI needs to drive its own local simulation.

/** Fixed opponent count for the local mock draft (plan T7 hard constraint). */
export const MOCK_DRAFT_TEAMS = 8;

/**
 * Exact reason string from engine/draft_sim.py's `_reasons()`. DraftSessionPanel
 * de-emphasizes this one specifically when it applies to every shown
 * recommendation (thin-pool artifact, reviewed T4 finding) — that logic
 * silently stops working if the backend rewords the string, so
 * draftSession.test.ts reads the backend source directly and asserts this
 * constant is still exactly what it prints, rather than trusting the two
 * files to stay in sync by convention.
 */
export const MAY_NOT_LAST_REASON = "May not last until your next pick";

export interface DraftPick {
  playerKey: string;
  name: string;
  position: string | null;
}

/**
 * Rounds for the local mock draft, derived from the actual draftable pool
 * size so the simulation can never run out of players to hand to opponents.
 * Caps at 9 (the plan's stated 8x9 default = 72 picks) but shrinks for a
 * smaller pool instead of hardcoding 72 anywhere.
 */
export function mockDraftRounds(poolSize: number, teams: number = MOCK_DRAFT_TEAMS): number {
  if (teams < 1) return 0;
  return Math.max(0, Math.min(9, Math.floor(poolSize / teams)));
}

/** 1-based team index on the clock for `overallPick` in a snake draft. */
export function snakeTeamForPick(overallPick: number, teams: number): number {
  const round = Math.floor((overallPick - 1) / teams) + 1;
  const posInRound = overallPick - (round - 1) * teams; // 1-based
  return round % 2 === 1 ? posInRound : teams - posInRound + 1;
}

/** 1-based round number for `overallPick`. */
export function pickRound(overallPick: number, teams: number): number {
  return Math.floor((overallPick - 1) / teams) + 1;
}

/**
 * mulberry32 PRNG: a tiny, dependency-free deterministic generator. Same
 * seed -> same sequence forever, which is what makes opponent picks
 * "reproducible" (testable, debuggable) while still varying across
 * `Reset mock draft` -- each reset mints a fresh seed (Date.now()-based) so
 * the mock draft doesn't replay an identical board every time (review fix).
 */
export function mulberry32(seed: number): () => number {
  let t = seed >>> 0;
  return function nextRandom() {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

// mirrors engine/draft_sim.py's _OPPONENT_PICK_WEIGHTS (D3: opponents favor
// the top of the ADP list but aren't purely rational -- weights taper fast
// so upsets are rare but possible)
const OPPONENT_PICK_WEIGHTS = [8, 4, 2, 1, 1] as const;

/**
 * Weighted-random pick among the top of `candidates` (already ADP-ordered),
 * drawing from `rng()` in [0, 1). Falls back gracefully once fewer
 * candidates remain than there are weights. Returns null on an empty list.
 */
export function weightedAdpPick<T>(candidates: T[], rng: () => number): T | null {
  if (candidates.length === 0) return null;
  const pool = candidates.slice(0, OPPONENT_PICK_WEIGHTS.length);
  const weights = OPPONENT_PICK_WEIGHTS.slice(0, pool.length);
  const total = weights.reduce((a, b) => a + b, 0);
  let roll = rng() * total;
  for (let i = 0; i < pool.length; i++) {
    roll -= weights[i];
    if (roll < 0) return pool[i];
  }
  return pool[pool.length - 1];
}
