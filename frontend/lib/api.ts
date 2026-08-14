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

// --- GET /api/leagues/{id}/matchup ---

export interface WeekRange {
  start_date: string;
  end_date: string;
  // true when Yahoo didn't supply week_start/week_end and the range was
  // derived from the configured season start instead -- the UI must say so
  is_derived: boolean;
}

export interface WeeklyProjectionOut {
  // the 9 CATEGORIES keys; fg_pct/ft_pct are ratios, the rest are sums
  totals: Record<string, number>;
  // the raw fgm/fga/ftm/fta totals fg_pct/ft_pct were derived from
  components: Record<string, number>;
  games: number;
  // per-player games this week, keyed by yahoo_player_key -- lets the UI
  // show why a player did or didn't contribute (e.g. 0 games -> bye/injury)
  player_games: Record<string, number>;
}

export interface MatchupSide {
  team_id: number;
  team_key: string;
  name: string;
  projection: WeeklyProjectionOut;
  build_profile: BuildProfile;
}

export interface MatchupCategoryVerdict {
  category: string;
  mine: number;
  theirs: number;
  // my advantage, already tov-oriented so positive always means "winning"
  margin: number;
  // "winning" | "losing" | "close" | "tie"
  verdict: string;
}

export interface MatchupComparisonResult {
  categories: MatchupCategoryVerdict[];
  projected_score: [number, number];
  close_categories: string[];
  // close_categories ranked most-flippable first
  focus: string[];
}

export interface ScheduleCoverage {
  mine_games: number;
  opponent_games: number | null;
  // false when either side counted zero games -- the missing-schedule guard;
  // the UI must show a warning instead of the raw (misleadingly confident) 0-0
  ok: boolean;
}

export interface StreamSlot {
  day: string;
  player_key: string;
  // display fields resolved server-side from the same draftable rows the
  // draft board/adds endpoint use, so a slot never renders as "Player #<id>"
  name: string;
  position: string | null;
  nba_person_id: number;
  headshot_url: string | null;
  games_added: number;
  categories_helped: string[];
  // structured tokens ("category:<key>" | "back_to_back"), never English prose
  reason: string[];
}

export interface StreamingPlan {
  slots: StreamSlot[];
  adds_used: number;
  adds_reserved: number;
  // structured tokens, e.g. "no_candidates" | "no_close_categories" |
  // "no_adds_available" | "invalid_window" | "no_games_in_window" |
  // "no_positive_value_remaining"
  notes: string[];
  // "remaining" -- as_of fell inside the week, plan covers today through
  // week end (these are adds still actionable today); "full_week" -- as_of
  // fell outside the week (already over, or not started), plan covers the
  // whole week instead of returning empty. The UI must not present a
  // "full_week" plan as adds you can still make today.
  window_basis: "remaining" | "full_week";
}

export interface LeagueMatchupResponse {
  week: number;
  week_range: WeekRange;
  // the date streaming.slots were computed relative to
  as_of: string;
  mine: MatchupSide;
  // null when the opponent couldn't be identified this call -- see opponent_reason
  opponent: MatchupSide | null;
  // structured token, e.g. "yahoo_unavailable" | "no_matchup_this_week" |
  // "no_opponent_in_matchup" | "opponent_team_not_synced"; null when opponent is set
  opponent_reason: string | null;
  // null whenever opponent is null -- a comparison needs both sides
  comparison: MatchupComparisonResult | null;
  schedule_coverage: ScheduleCoverage;
  // null whenever opponent is null -- close_categories has no meaning without one
  streaming: StreamingPlan | null;
  stale: boolean;
  synced_at: string;
}

export interface DraftBoardPlayer {
  player_key: string;
  name: string;
  position: string | null;
  nba_person_id: number;
  headshot_url: string | null;
  best_class: string;
  projected_games: number;
  base: number;
  vorp: number;
  value: number;
  replacement: number;
  zscores: Record<string, unknown>;
  // "projection" or "season_average" -- lets the UI show the fallback honestly.
  // Distinct from DraftBoardResponse.source (the projection SOURCE NAME).
  stat_basis: string;
}

export interface DraftPuntSuggestion {
  // canonical-order category keys (never the engine's raw hash-ordered set)
  punt: string[];
  score: number;
  improvement: number;
  pool_delta: number;
  weakest: string;
  weakest_mean: number;
  rationale: string;
}

export interface DraftBoardResponse {
  players: DraftBoardPlayer[];
  punt_suggestions: DraftPuntSuggestion[];
  // the projection source actually used, or null when the board is valued
  // purely off season averages (no projections synced yet)
  source: string | null;
  stale: boolean;
  synced_at: string;
}

export interface DraftRecommendation {
  player_key: string;
  name: string;
  position: string | null;
  value: number;
  rank_score: number;
  reasons: string[];
  need_cats: string[];
}

export interface DraftRecommendResponse {
  recommendations: DraftRecommendation[];
  stale: boolean;
  synced_at: string;
}

export interface DraftRecommendRequest {
  my_player_keys: string[];
  taken_player_keys: string[];
  overall_pick: number;
  punt?: string[];
  limit?: number;
  source?: string;
}

// --- GET /api/leagues/{id}/adds ---

export interface AddsCandidate {
  player_key: string;
  name: string;
  position: string | null;
  nba_person_id: number;
  headshot_url: string | null;
  score: number;
  games_remaining: number;
  categories_helped: string[];
  // "projection" or "season_average" -- same fallback-honesty field the
  // draft board carries
  stat_basis: string;
  // structured tokens, e.g. "category:<key>" | "schedule_driven" |
  // "season_average_fallback", never English prose
  reasons: string[];
}

export interface LeagueAddsResponse {
  week: number;
  week_range: WeekRange;
  as_of: string;
  window_basis: "remaining" | "full_week";
  // categories the ranking is weighted toward from this week's matchup;
  // empty when opponent_reason is set -- ranking degrades to roster need alone
  close_categories: string[];
  // structured token (same vocabulary as LeagueMatchupResponse), null when a
  // real opponent was found and close_categories reflects it; set otherwise
  // so the page can say it's ranking on need alone
  opponent_reason: string | null;
  candidates: AddsCandidate[];
  schedule_coverage: ScheduleCoverage;
  stale: boolean;
  synced_at: string;
}

// --- GET /api/leagues/{id}/trades ---

export interface TradeCategoryStrength {
  category: string;
  total: number;
  mean: number;
  // "strong" | "average" | "punt"
  label: string;
  // how many rostered players meaningfully contribute to this category
  depth: number;
  // true when this category reads "strong" only because of one dominant
  // contributor -- excluded from surplus (trading them collapses it, not
  // just weakens it)
  fragile: boolean;
  top_contributor: string | null;
  top_share: number;
}

export interface TradeSide {
  team_id: number;
  // keyed by the 9 CATEGORIES
  categories: Record<string, TradeCategoryStrength>;
  surplus: string[];
  deficit: string[];
}

export interface TradePlayerInfo {
  name: string;
  position: string | null;
  nba_person_id: number;
  headshot_url: string | null;
}

export interface TradeProfile {
  totals: Record<string, number>;
  labels: Record<string, string>;
  means: Record<string, number>;
}

export interface TradeSideOutcome {
  before: TradeProfile;
  after: TradeProfile;
  gained: string[];
  lost: string[];
  collapsed: string[];
}

export interface TradeVerdict {
  // player_key tuples (yahoo_player_key) -- resolve display info via
  // LeagueTradesResponse.players
  give: string[];
  get: string[];
  mine: TradeSideOutcome;
  theirs: TradeSideOutcome;
  net_value: number;
  // "favors_me" | "favors_them" | "balanced" | "rejected"
  verdict: string;
  // structured tokens, e.g. "gained:<cat>" | "lost:<cat>" | "collapsed:<cat>" |
  // "no_downside" | "rejected", never English prose
  reasons: string[];
}

export interface LeagueTradesResponse {
  mine: TradeSide;
  theirs: TradeSide;
  // display info for every player_key referenced anywhere in mine/theirs or
  // a verdict's give/get, keyed by yahoo_player_key
  players: Record<string, TradePlayerInfo>;
  verdicts: TradeVerdict[];
  // how many give/get combinations were actually examined
  evaluated: number;
  // true iff the internal candidate cap stopped generation before it
  // finished -- the plan forbids silent truncation, so the UI must disclose this
  truncated: boolean;
  // always "category_impact_only" today: net_value/verdict weigh category
  // impact, not positional scarcity (the evaluator has no position data) --
  // the UI must disclose this limitation, not present the verdict as complete
  value_basis: string;
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

export function getLeagueMatchup(
  id: number,
  opts?: { week?: number; asOf?: string }
): Promise<LeagueMatchupResponse> {
  const params = new URLSearchParams();
  if (opts?.week !== undefined) params.set("week", String(opts.week));
  // asOf is an ISO date string ("YYYY-MM-DD"); the backend defaults it to
  // today when omitted, so this is only sent when the caller wants a
  // specific streaming-window anchor (e.g. viewing a past/future week)
  if (opts?.asOf) params.set("as_of", opts.asOf);
  const qs = params.toString();
  return requestJson<LeagueMatchupResponse>(`/api/leagues/${id}/matchup${qs ? `?${qs}` : ""}`);
}

export function refreshLeague(id: number): Promise<void> {
  return requestVoid(`/api/leagues/${id}/refresh`, { method: "POST" });
}

export function getLeagueAdds(
  id: number,
  opts?: { week?: number; asOf?: string; punt?: string[]; limit?: number }
): Promise<LeagueAddsResponse> {
  const params = new URLSearchParams();
  if (opts?.week !== undefined) params.set("week", String(opts.week));
  if (opts?.asOf) params.set("as_of", opts.asOf);
  // repeated ?punt=cat query params, same convention as getDraftBoard
  for (const cat of opts?.punt ?? []) params.append("punt", cat);
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return requestJson<LeagueAddsResponse>(`/api/leagues/${id}/adds${qs ? `?${qs}` : ""}`);
}

export function getLeagueTrades(
  id: number,
  teamId: number,
  opts?: { maxPackage?: number; limit?: number }
): Promise<LeagueTradesResponse> {
  const params = new URLSearchParams();
  params.set("team_id", String(teamId));
  if (opts?.maxPackage !== undefined) params.set("max_package", String(opts.maxPackage));
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  return requestJson<LeagueTradesResponse>(`/api/leagues/${id}/trades?${params.toString()}`);
}

export function getDraftBoard(
  id: number,
  opts?: { source?: string; punt?: string[]; myPlayerKeys?: string[] }
): Promise<DraftBoardResponse> {
  const params = new URLSearchParams();
  if (opts?.source) params.set("source", opts.source);
  // repeated ?punt=cat query params -- FastAPI's list[str] query binding expects
  // one entry per occurrence, not a comma-joined value
  for (const cat of opts?.punt ?? []) params.append("punt", cat);
  // repeated ?my_player_key= -- lets a mock draft (no Yahoo roster yet) supply
  // its own picks as the punt advisor's roster basis instead of the league roster
  for (const key of opts?.myPlayerKeys ?? []) params.append("my_player_key", key);
  const qs = params.toString();
  return requestJson<DraftBoardResponse>(`/api/leagues/${id}/draft/board${qs ? `?${qs}` : ""}`);
}

export function postDraftRecommend(
  id: number,
  body: DraftRecommendRequest
): Promise<DraftRecommendResponse> {
  return requestJson<DraftRecommendResponse>(`/api/leagues/${id}/draft/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function disconnectYahoo(): Promise<void> {
  return requestVoid("/api/account/disconnect", { method: "POST" });
}

export function deleteAccount(): Promise<void> {
  return requestVoid("/api/account", { method: "DELETE" });
}
