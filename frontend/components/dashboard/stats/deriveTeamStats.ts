import type { LeagueOverviewResponse, LeagueTeamResponse } from "@/lib/api";
import { classifyBuildLabel } from "@/components/dashboard/format";

export interface DerivedTeamStats {
  /** "W-L-T" from the caller's own standings row (matched via overview.my_team_id),
   * or null when the league is unclaimed (my_team_id is null) or no row matches. */
  record: string | null;
  /** "rank/total" against overview.standings.length, same nullability as record. */
  rank: string | null;
  /** Up to two build-profile contract keys (see categoryKeys.ts) the backend
   * itself labelled "strong" (see BuildProfile.tsx), highest mean first. Never
   * derived from the raw number alone -- a category with no "strong" label
   * cannot appear here even if its mean is the highest in the payload. */
  strongest: string[];
  /** Up to two build-profile contract keys the backend labelled "punt", worst
   * mean first. Same label-gated rule as `strongest`. */
  weakest: string[];
}

/**
 * Derives the My Team summary tiles from the two payloads the page already
 * fetches -- no new fetch is ever added here, per the tile rule: a tile ships
 * only if it's derivable from an existing response.
 */
export function deriveTeamStats(
  overview: LeagueOverviewResponse,
  team: LeagueTeamResponse,
): DerivedTeamStats {
  // my_team_id is null for an unclaimed/unlinked league -- a real state the
  // overview endpoint returns, not an error, so record/rank must degrade to
  // null rather than throw on a missing row
  const myRow =
    overview.my_team_id !== null
      ? overview.standings.find((row) => row.team_id === overview.my_team_id)
      : undefined;

  const record = myRow ? `${myRow.wins}-${myRow.losses}-${myRow.ties}` : null;
  const rank = myRow ? `${myRow.rank}/${overview.standings.length}` : null;

  // means is keyed by contract key and, per the backend's engine.zscores
  // module, every category (tov included) is already oriented "higher is
  // better" before it reaches this payload -- so a plain numeric sort works
  // uniformly across all 9 categories, no per-category direction handling
  const entries = Object.entries(team.build_profile.means ?? {}).filter(
    (entry): entry is [string, number] =>
      typeof entry[1] === "number" && Number.isFinite(entry[1]),
  );

  // labels is the same loose Record<string, unknown> shape as means -- guard
  // it the same way instead of assuming the backend always sends strings
  const labels = team.build_profile.labels ?? {};

  // gate on the backend's own classification (see BuildProfile.tsx / format.ts
  // classifyBuildLabel), never on the raw number alone: a tile must never
  // assert a strength/weakness the Category build panel underneath doesn't
  // also show. This also means an all-"average" or all-zero build profile
  // (e.g. no roster player mapped to an NBA id) correctly yields two empty
  // lists instead of two confident, meaningless picks.
  const strongEntries = entries.filter(([key]) => classifyBuildLabel(labels[key]) === "strong");
  const puntEntries = entries.filter(([key]) => classifyBuildLabel(labels[key]) === "punt");

  // most extreme first in both lists: strongest sorts descending (highest
  // mean first), weakest sorts ascending (lowest/worst mean first) -- the old
  // code sliced the tail of a descending sort without reversing, so the worst
  // category read second instead of first
  const strongestSorted = [...strongEntries].sort((a, b) => b[1] - a[1]);
  const weakestSorted = [...puntEntries].sort((a, b) => a[1] - b[1]);

  const strongest = strongestSorted.slice(0, 2).map(([key]) => key);
  const weakest = weakestSorted.slice(0, 2).map(([key]) => key);

  return { record, rank, strongest, weakest };
}
