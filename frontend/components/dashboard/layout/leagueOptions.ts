import type { League } from "@/lib/api";

export interface LeagueOption {
  id: string;
  name: string;
  disabled?: boolean;
}

/**
 * Builds the league-switcher <select>'s options from getMe()'s (possibly
 * still-loading, possibly empty, possibly stale) leagues array. Three honest
 * states, not one indefinite "Loading…":
 *   - leagues empty + not yet settled: still loading.
 *   - leagues empty + settled: getMe errored or the account has zero leagues
 *     (the layout swallows non-unauthorized getMe errors, so this is
 *     reachable and permanent, not a transient flash) -- a terminal label,
 *     never "Loading…" forever.
 *   - leagues present: normal options, plus a guard entry if the routed
 *     league id isn't among them (stale bookmark, removed league, another
 *     account's id) so a controlled <select> never silently falls back to
 *     showing its first option as selected while the URL points elsewhere.
 */
export function buildLeagueOptions({
  leagueId,
  leagueName,
  leagues,
  leaguesLoaded,
}: {
  leagueId: string;
  leagueName: string | null;
  leagues: League[];
  leaguesLoaded: boolean;
}): LeagueOption[] {
  if (leagues.length === 0) {
    return [{ id: leagueId, name: leaguesLoaded ? "League unavailable" : "Loading…" }];
  }

  const options = leagues.map((l) => ({ id: String(l.id), name: l.name }));
  if (options.some((option) => option.id === leagueId)) {
    return options;
  }

  // routed id matches none of the fetched leagues -- prepend a disabled
  // placeholder standing in for it so the control can't misreport which
  // league the rest of the page is actually showing
  return [{ id: leagueId, name: leagueName ?? "Unknown league", disabled: true }, ...options];
}
