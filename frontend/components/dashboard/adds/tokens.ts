// Structured-token translation for the Adds page. Mirrors
// components/dashboard/matchup/tokens.ts's discipline exactly: the engine
// only ever emits contract-key tokens (see engine.REASON_TOKENS and
// backend/src/ninecat/engine/waivers.py's module docstring for the
// authoritative vocabulary), and every FIXED token is typed as an explicit
// union so a new one landing on the backend without a matching entry here
// is a TypeScript compile error, not a silently prose-ified unknown string
// reaching the screen. That bug class (a raw contract key, or an unknown
// token humanized into fluent-looking copy) has shipped twice in this
// project already.
import { LABEL_BY_CONTRACT_KEY } from "@/components/dashboard/categoryKeys";

// AddsCandidate.reasons' two non-category tokens (engine.waivers
// REASON_SCHEDULE_DRIVEN / REASON_SEASON_AVERAGE_FALLBACK). "category:<key>"
// tokens are handled generically below since there's one per CATEGORIES key.
export const STATIC_REASON_TOKENS = ["schedule_driven", "season_average_fallback"] as const;
type StaticReasonToken = (typeof STATIC_REASON_TOKENS)[number];

const STATIC_REASON_LABEL: Record<StaticReasonToken, string> = {
  schedule_driven:
    "Plays a full game more than most of this free-agent pool this week — schedule is doing real work here",
  season_average_fallback: "Valued off last season's averages, not a live projection",
};

function isStaticReasonToken(token: string): token is StaticReasonToken {
  return (STATIC_REASON_TOKENS as readonly string[]).includes(token);
}

/**
 * One AddsCandidate.reasons token: "category:<key>" | "schedule_driven" |
 * "season_average_fallback". The category branch is generic (not an
 * exhaustive map) because there's one token per CATEGORIES entry, but it
 * still never prints a bare/unrecognized key — same "Helps <fallback>"
 * framing as the matchup page's streaming reasons.
 */
export function describeReason(token: string): string {
  if (token.startsWith("category:")) {
    const key = token.slice("category:".length);
    const label = LABEL_BY_CONTRACT_KEY[key];
    // keeps the key on the unknown branch: "Helps an unrecognized category"
    // was a grammatical, intentional-looking sentence that gave neither the
    // user nor whoever chases it anything to go on
    return label ? `Helps ${label}` : `Helps an unrecognized category (${key})`;
  }
  if (isStaticReasonToken(token)) return STATIC_REASON_LABEL[token];
  // forward-compatible fallback for a token this file doesn't know about yet
  return `Unrecognized reason (${token})`;
}

// LeagueAddsResponse.opponent_reason -- same vocabulary and same four values
// the matchup page already surfaces (backend's OPPONENT_REASON_* constants,
// api/routes.py, shared by both endpoints via _resolve_week_and_opponent).
// Kept as its own explicit union here (rather than imported, since the
// matchup page's copy lives in a component, not an exported map) so this
// file independently breaks at compile time if the backend adds a fifth.
export const OPPONENT_REASON_TOKENS = [
  "yahoo_unavailable",
  "no_matchup_this_week",
  "no_opponent_in_matchup",
  "opponent_team_not_synced",
] as const;
type OpponentReasonToken = (typeof OPPONENT_REASON_TOKENS)[number];

const OPPONENT_REASON_LABEL: Record<OpponentReasonToken, string> = {
  yahoo_unavailable: "Yahoo's matchup data isn't reachable right now — try refreshing in a moment.",
  no_matchup_this_week:
    "There's no matchup scheduled this week (bye week, playoffs gap, or off-season).",
  no_opponent_in_matchup: "This week's matchup doesn't list an opposing team.",
  opponent_team_not_synced:
    "Your opponent hasn't synced into NineCat yet — check back after their next league sync.",
};

function isOpponentReasonToken(token: string): token is OpponentReasonToken {
  return (OPPONENT_REASON_TOKENS as readonly string[]).includes(token);
}

/**
 * LeagueAddsResponse.opponent_reason. This is the reason the ranking fell
 * back to roster need alone instead of this week's matchup — an unknown
 * token surfaces as a visible gap, never quietly humanized into something
 * that reads like an intentional explanation.
 */
export function describeOpponentReason(token: string): string {
  if (isOpponentReasonToken(token)) return OPPONENT_REASON_LABEL[token];
  return `Unrecognized status (${token}) — this note needs a translation.`;
}
