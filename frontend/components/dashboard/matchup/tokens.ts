// Structured-token translation for the add-schedule optimizer's output.
// plan_streaming (backend) emits "reason"/"notes" as fixed contract tokens,
// never English prose — see engine/matchup.py and the streaming module
// docstrings — so this is the one place they become words, mirroring
// categoryKeys.ts's role for the 9 category keys. A raw token must never
// reach the page (the draft board shipped exactly that bug once, and this
// page nearly shipped a second instance — see NOTE_TOKENS below).
import { LABEL_BY_CONTRACT_KEY } from "@/components/dashboard/categoryKeys";

/** One streaming-slot reason token: "category:<key>" | "back_to_back" | (forward-compat unknown). */
export function describeReason(token: string): string {
  if (token === "back_to_back") return "Back-to-back games";
  if (token.startsWith("category:")) {
    const key = token.slice("category:".length);
    const label = LABEL_BY_CONTRACT_KEY[key];
    // even the fallback never prints the bare contract key alone — it's
    // still framed as "Helps X" so it reads as a reason, not a stray token
    return `Helps ${label ?? "an unrecognized category"}`;
  }
  // forward-compatible fallback for a token this file doesn't know about yet
  return `Unrecognized reason (${token})`;
}

// mirrors engine.NOTE_TOKENS (backend's plan_streaming vocabulary) — kept as
// an explicit list, not inferred from NOTE_LABEL's keys, so adding a new
// backend token that this file forgets to translate is a type error here,
// not a silent runtime fallback. This list must be updated by hand whenever
// engine.NOTE_TOKENS gains an entry (no shared package to import it from).
export const NOTE_TOKENS = [
  "no_candidates",
  "no_close_categories",
  "no_adds_available",
  "invalid_window",
  "no_games_in_window",
  "no_positive_value_remaining",
] as const;
type NoteToken = (typeof NOTE_TOKENS)[number];

const NOTE_LABEL: Record<NoteToken, string> = {
  no_candidates: "No streaming candidates were available this week.",
  no_close_categories: "No categories are close enough to be worth streaming for.",
  no_adds_available: "Your weekly add budget is already used up.",
  invalid_window: "The streaming window couldn't be computed for this date.",
  no_games_in_window: "The candidates found don't have any games left in this window.",
  no_positive_value_remaining: "No remaining candidate would help enough to be worth an add.",
};

function isNoteToken(token: string): token is NoteToken {
  return (NOTE_TOKENS as readonly string[]).includes(token);
}

/**
 * One StreamingPlan.notes token. An unrecognized token is surfaced as a
 * visible gap ("needs a translation"), never quietly humanized into
 * something that reads like real copy — a smoothly-prose-ified unknown
 * token is exactly what let "no_games_in_window" hide in review once already.
 */
export function describeNote(token: string): string {
  if (isNoteToken(token)) return NOTE_LABEL[token];
  return `Unrecognized status (${token}) — this note needs a translation.`;
}
