// Typed client for the NineCat backend. All calls are same-origin — next.config.ts
// rewrites /api/* to the FastAPI backend so the session cookie stays first-party.

export interface League {
  id: number;
  yahoo_league_key: string;
  name: string;
  season: string;
  synced_at: string | null;
}

export interface MeResponse {
  display_name: string;
  leagues: League[];
}

export interface StandingsEntry {
  team_id: number;
  name: string;
  rank: number;
  wins: number;
  losses: number;
  ties: number;
}

export interface MatchupTeam {
  name: string;
  category_totals: Record<string, unknown>;
}

export interface Matchup {
  week: number;
  teams: MatchupTeam[];
}

export interface LeagueOverviewResponse {
  standings: StandingsEntry[];
  // the caller's own team id in this league, or null if unclaimed/unlinked —
  // lets the UI highlight "my" standings row without guessing from matchup order
  my_team_id: number | null;
  matchup: Matchup | null;
  stale: boolean;
  synced_at: string;
}

export interface RosterPlayer {
  yahoo_player_key: string;
  name: string;
  position: string;
  injury_status: string | null;
  headshot_url: string | null;
  averages: Record<string, unknown> | null;
}

export interface BuildProfile {
  totals: Record<string, unknown>;
  labels: Record<string, unknown>;
  means: Record<string, unknown>;
}

export interface LeagueTeamResponse {
  roster: RosterPlayer[];
  build_profile: BuildProfile;
  stale: boolean;
  synced_at: string;
}

/** Thrown for any non-2xx response; callers switch on `status` (e.g. 401 -> redirect to "/"). */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Type guard so pages can redirect on 401 without a manual instanceof + status check. */
export function isUnauthorized(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 401;
}

// shared fetch + error handling; leaves success-path body handling to the caller
// since JSON-returning and void endpoints need different treatment on 2xx.
async function fetchOk(path: string, init?: RequestInit): Promise<Response> {
  // cache: "no-store" — dashboard data is per-session and must never be served from the
  // Next.js fetch cache; credentials default to "same-origin" already, which is what we want
  // now that /api/* is rewritten to the backend under the same origin.
  const res = await fetch(path, { ...init, cache: "no-store" });

  if (!res.ok) {
    // error bodies aren't guaranteed to be JSON (e.g. a proxy 502 or plain-text 500);
    // swallow parse failures so a bad body never masks the real status code.
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = undefined;
    }
    throw new ApiError(`Request to ${path} failed with status ${res.status}`, res.status, body);
  }

  return res;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchOk(path, init);
  // a 2xx with a malformed/empty body (e.g. misconfigured proxy) must surface as an
  // ApiError, not a raw SyntaxError, so callers only ever need to catch ApiError.
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(`Request to ${path} returned invalid JSON`, res.status);
  }
}

async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  // void endpoints (refresh/disconnect/delete) ignore the body on any 2xx — some
  // backends return 200 with an empty or text body instead of a strict 204, and
  // parsing it would risk throwing on content we never intended to use anyway.
  await fetchOk(path, init);
}

export function getMe(): Promise<MeResponse> {
  return requestJson<MeResponse>("/api/me");
}

export function syncLeagues(): Promise<League[]> {
  return requestJson<League[]>("/api/sync", { method: "POST" });
}

export function getLeagueOverview(id: number): Promise<LeagueOverviewResponse> {
  return requestJson<LeagueOverviewResponse>(`/api/leagues/${id}/overview`);
}

export function getLeagueTeam(id: number): Promise<LeagueTeamResponse> {
  return requestJson<LeagueTeamResponse>(`/api/leagues/${id}/team`);
}

export function refreshLeague(id: number): Promise<void> {
  return requestVoid(`/api/leagues/${id}/refresh`, { method: "POST" });
}

export function disconnectYahoo(): Promise<void> {
  return requestVoid("/api/account/disconnect", { method: "POST" });
}

export function deleteAccount(): Promise<void> {
  return requestVoid("/api/account", { method: "DELETE" });
}
