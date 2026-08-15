import type { LeagueMatchupResponse } from "@/lib/api";

export interface DerivedMatchupStats {
  /** Straight passthrough of the response's week number -- always known, even
   * when there's no opponent or comparison this week. */
  week: number;
  /** The opposing team's name, or null when the response has no opponent
   * (see LeagueMatchupResponse.opponent -- OpponentEmptyState renders that
   * case; a real, reachable production state, not an error). */
  opponent: string | null;
  /** "mine-theirs" projected category score, or null whenever `comparison`
   * is null -- which happens both when there's no opponent AND, separately,
   * when schedule_coverage isn't ok even with a known opponent (see
   * ScheduleCoverageNotice), so this can't be gated on opponent alone. */
  projected: string | null;
  /** Count of categories verdict-labelled "winning" for my side. Counts only
   * the "winning" verdict, not "close" -- a close category can still carry a
   * slim numeric lead (see backend engine/matchup.py's _classify), but the
   * verdict itself deliberately doesn't call that a solid lead, and this tile
   * is meant to answer the same question the verdict badges do, not
   * recompute a different one from raw margins. Ties (verdict "tie") are
   * naturally excluded since only "winning" counts. Null under the same
   * comparison-null conditions as `projected`. */
  categoriesLed: number | null;
}

/**
 * Derives the Matchup summary tiles from the single response the page
 * already fetches -- no new fetch, per the tile rule: a tile ships only if
 * it's derivable from data the page already has. Reads the existing
 * per-category `verdict` field for categoriesLed rather than recomputing a
 * win/loss comparison from `margin`, so this can never disagree with the
 * verdict badges rendered elsewhere on the page.
 */
export function deriveMatchupStats(matchup: LeagueMatchupResponse): DerivedMatchupStats {
  const { week, opponent, comparison } = matchup;

  if (!opponent || !comparison) {
    return {
      week,
      opponent: opponent?.name ?? null,
      projected: null,
      categoriesLed: null,
    };
  }

  const [mineWins, theirWins] = comparison.projected_score;
  const categoriesLed = comparison.categories.filter((cv) => cv.verdict === "winning").length;

  return {
    week,
    opponent: opponent.name,
    projected: `${mineWins}-${theirWins}`,
    categoriesLed,
  };
}
