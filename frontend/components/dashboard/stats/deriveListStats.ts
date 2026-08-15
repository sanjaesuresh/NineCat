import type { LeagueAddsResponse, LeagueTradesResponse } from "@/lib/api";
import { isVerdictToken, VERDICT_LABEL } from "@/components/dashboard/trades/tokens";

export interface DerivedAddsStats {
  /** Count of the ranked candidates the response actually returned (already
   * capped to ADDS_LIMIT server-side via the `limit` query param the page
   * sends) -- not a total pool size, since the response carries no separate
   * total. */
  candidates: number;
}

/**
 * Derives the Adds summary tile from the single response the page already
 * fetches -- no new fetch, per the tile rule: a tile ships only if it's
 * derivable from data the page already has.
 *
 * A "weekly adds remaining" tile was planned but is dropped here: nothing in
 * LeagueAddsResponse (or anywhere else in lib/api.ts) reports a per-week add
 * cap or a remaining-adds count -- Yahoo's transaction-limit settings are
 * never fetched by this page. Inventing a value would violate the tile rule
 * ("ship fewer tiles, do NOT invent one"), so this page gets one tile.
 */
export function deriveAddsStats(adds: LeagueAddsResponse): DerivedAddsStats {
  return {
    candidates: adds.candidates.length,
  };
}

export interface DerivedTradesStats {
  /** Count of proposed trade verdicts in the response. */
  proposals: number;
  /** Display label of the highest-ranked proposal (verdicts[0], the same
   * "rank 1" the page itself assigns via `verdicts.map((v, i) => ...)`), or
   * null when there are no proposals. Reads trades/tokens.ts's VERDICT_LABEL
   * -- the same source TradeVerdictBadge reads for the pill on that same top
   * card -- so this tile can never disagree with the badge next to it. */
  bestVerdict: string | null;
}

/**
 * Derives the Trades summary tiles from the single response the page already
 * fetches -- no new fetch, per the tile rule.
 */
export function deriveTradesStats(trades: LeagueTradesResponse): DerivedTradesStats {
  const [top] = trades.verdicts;
  const bestVerdict = top
    ? (isVerdictToken(top.verdict) ? VERDICT_LABEL[top.verdict] : `Unrecognized verdict (${top.verdict})`)
    : null;

  return {
    proposals: trades.verdicts.length,
    bestVerdict,
  };
}
