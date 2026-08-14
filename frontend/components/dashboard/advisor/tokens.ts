// Structured-token translation for the Claude advisor. Same discipline as
// components/dashboard/adds/tokens.ts: the backend only ever emits contract-key
// tokens (backend/src/ninecat/advisor/types.py's REASON_* constants are the
// authoritative vocabulary), and every one is typed as an explicit union so a
// new token landing on the backend without a matching entry here is a
// TypeScript compile error rather than a raw key reaching the screen.
import type { ModelExplanations } from "@/lib/api";

export const EXPLANATIONS_REASON_TOKENS = [
  "not_configured",
  "timeout",
  "rate_limited",
  "auth_error",
  "connection_error",
  "overloaded",
  "api_error",
  "refused",
  "malformed_response",
  "shortlist_mismatch",
  "empty_shortlist",
] as const;
type ExplanationsReasonToken = (typeof EXPLANATIONS_REASON_TOKENS)[number];

// Grouped by what the user can actually do about it, not by the backend's
// internal taxonomy. The rankings are the engine's either way, so every line
// says that plainly rather than implying something is broken about the page.
const REASON_LABEL: Record<ExplanationsReasonToken, string> = {
  not_configured:
    "Written explanations are turned off for this install. The ranking below is the engine's own.",
  timeout: "The explanation service didn't answer in time. The ranking below is the engine's own.",
  connection_error:
    "The explanation service couldn't be reached. The ranking below is the engine's own.",
  rate_limited:
    "The explanation service is rate-limited right now. The ranking below is the engine's own.",
  overloaded:
    "The explanation service is overloaded right now. The ranking below is the engine's own.",
  api_error: "The explanation service returned an error. The ranking below is the engine's own.",
  auth_error:
    "The explanation service rejected our credentials — this one needs an admin. The ranking below is the engine's own.",
  refused: "The model declined to answer this one. The ranking below is the engine's own.",
  // these two are the guard working, and they say so: a wrong-looking answer
  // was thrown away rather than shown. That is the honest framing -- a
  // plausible explanation for a player the engine never shortlisted would be
  // worse than none at all.
  malformed_response:
    "The model's answer didn't check out, so it was discarded. The ranking below is the engine's own.",
  shortlist_mismatch:
    "The model's answer named players the engine hadn't shortlisted, so it was discarded. The ranking below is the engine's own.",
  // there is nothing to explain, and the empty state above already says so --
  // a second note here would be noise
  empty_shortlist: "",
};

function isReasonToken(token: string): token is ExplanationsReasonToken {
  return (EXPLANATIONS_REASON_TOKENS as readonly string[]).includes(token);
}

/**
 * One `explanations_reason` token. Returns null when there is nothing worth
 * saying; an unknown token surfaces as a visible gap rather than being quietly
 * humanized into copy that reads intentional.
 */
export function describeExplanationsReason(token: string | null): string | null {
  if (token === null) return null;
  if (isReasonToken(token)) return REASON_LABEL[token] || null;
  return `Explanations are unavailable for an unrecognized reason (${token}).`;
}

/**
 * item_key -> reasoning, for rendering each explanation next to the row it
 * is about.
 *
 * Deliberately keyed rather than zipped by position: the model's order and the
 * engine's order are allowed to differ (reordering is the one thing it may do),
 * so pairing by index would attach the wrong prose to the wrong row.
 */
export function reasoningByItemKey(
  explanations: ModelExplanations | null,
): Map<string, string> {
  if (!explanations) return new Map();
  return new Map(explanations.ranked.map((e) => [e.item_key, e.reasoning]));
}

/**
 * The model's rank (1-based) for each item_key, or an empty map when there
 * are no explanations. Lets a list show where the model disagreed with the
 * engine's ordering instead of silently re-sorting the page underneath the user.
 */
export function modelRankByItemKey(
  explanations: ModelExplanations | null,
): Map<string, number> {
  if (!explanations) return new Map();
  return new Map(explanations.ranked.map((e, i) => [e.item_key, i + 1]));
}
