import { pickRound } from "@/components/dashboard/draft/draftSession";
import { LABEL_BY_CONTRACT_KEY } from "@/components/dashboard/categoryKeys";

export interface DerivedDraftStats {
  /** "current of total" overall pick, e.g. "9 of 72"; null once the mock
   * draft is complete. useDraftSession signals completion by letting
   * overallPick overshoot totalPicks (draftComplete = overallPick >
   * totalPicks), so there is no valid "N of M" to print past the last pick --
   * the Pick/Round tiles hide rather than show an impossible "73 of 72". */
  pick: string | null;
  /** 1-based round for `overallPick`, via the same `pickRound` helper the
   * mock-draft session uses -- never recomputed here, so the two can't drift.
   * Null alongside `pick` once complete, for the same reason. */
  round: number | null;
  /** Size of the draftable pool backing the current board. This is the
   * fixed board size, not a "players remaining" count -- it does not shrink
   * as picks are made, so callers must label it accordingly. */
  pool: number;
  /** Applied punt build, already translated to display labels (e.g. "REB",
   * not "reb") via LABEL_BY_CONTRACT_KEY -- callers render this directly
   * rather than re-deriving labels from the raw contract keys themselves.
   * Always a fresh array (Array#map), never the caller's own appliedPunt
   * reference, so a mutation of the returned array can't reach back into
   * React state. */
  puntLabels: string[];
}

export interface DeriveDraftStatsOptions {
  /** Current overall pick number (1-based), possibly overshooting `totalPicks`
   * once the draft is complete -- see `complete` below. */
  overallPick: number;
  /** Total picks in the mock draft (teams * rounds). */
  totalPicks: number;
  /** Team count backing the mock draft, passed through to `pickRound`. */
  teams: number;
  /** Size of the draftable pool backing the current board. */
  poolSize: number;
  /** Raw contract keys of the currently-applied punt build, untranslated. */
  appliedPunt: string[];
  /** True once the draft is done (overallPick has overshot totalPicks). */
  complete: boolean;
}

/**
 * Derives the Draft summary tiles from state the page already holds -- no new
 * fetch, per the tile rule: a tile ships only if it's derivable from data the
 * page already has.
 *
 * Takes a single options object rather than positional args: four of the
 * fields above are bare numbers, and this module is otherwise the only
 * derive*Stats module in this directory that isn't handed one typed payload
 * -- see layoutTokens.ts's tableRowClasses, which made the opposite choice
 * (named options over positional numbers) specifically so call sites can't
 * transpose two arguments and still compile.
 */
export function deriveDraftStats({
  overallPick,
  totalPicks,
  teams,
  poolSize,
  appliedPunt,
  complete,
}: DeriveDraftStatsOptions): DerivedDraftStats {
  return {
    pick: complete ? null : `${overallPick} of ${totalPicks}`,
    round: complete ? null : pickRound(overallPick, teams),
    pool: poolSize,
    puntLabels: appliedPunt.map((key) => LABEL_BY_CONTRACT_KEY[key] ?? key),
  };
}
