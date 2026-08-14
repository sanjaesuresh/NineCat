// Matchup-specific number/date formatting. Kept separate from the shared
// dashboard format.ts because:
//  - projected weekly totals need an integer-safe render (an exact 90 must
//    print "90", never "90.0" the way formatStatValue's unconditional
//    toFixed(1) would produce — the "612.0" bug the draft page shipped once)
//  - margins need a signed variant that still respects the FG%/FT% percent
//    scaling, which formatSignedNumber (draft valuation numbers) knows nothing about

const EM_DASH = "—";
const PERCENT_LABELS = new Set(["FG%", "FT%"]);

/** One projected category total (mine/theirs). Whole numbers render as "90", not "90.0". */
export function formatCategoryTotal(label: string, value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return EM_DASH;
  if (PERCENT_LABELS.has(label)) {
    // ratio (<=1) vs already-percent (>1): scale only the ratio form
    const percent = Math.abs(value) <= 1 ? value * 100 : value;
    return `${percent.toFixed(1)}%`;
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/**
 * Signed category margin — margin is already tov-oriented by the backend, so
 * positive always means "my advantage" here. FG%/FT% margins are labeled
 * "percentage points", never "pts" — this product also has a PTS category,
 * so an abbreviated "pts" on a percentage margin would misparse as points.
 */
export function formatMargin(label: string, value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return EM_DASH;
  const sign = value < 0 ? "−" : "+"; // U+2212 minus sign, not a hyphen
  const magnitude = Math.abs(value);
  if (PERCENT_LABELS.has(label)) {
    const percent = magnitude <= 1 ? magnitude * 100 : magnitude;
    return `${sign}${percent.toFixed(1)} percentage points`;
  }
  const rounded = Number.isInteger(magnitude) ? String(magnitude) : magnitude.toFixed(1);
  return `${sign}${rounded}`;
}

/**
 * "Dec 1 – Dec 7" style range for the week header. Never throws on a
 * malformed ISO date string, and never prints "null – null" — FantasyWeek
 * deliberately allows null start/end ("week known, not yet dated"), a state
 * the frontend contract types as non-null but that can occur at runtime, so
 * this accepts the wider type rather than trusting the declared one.
 */
export function formatWeekRange(
  startIso: string | null | undefined,
  endIso: string | null | undefined,
): string {
  if (!startIso || !endIso) return "Dates not set yet";
  const start = new Date(`${startIso}T00:00:00`);
  const end = new Date(`${endIso}T00:00:00`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return `${startIso} – ${endIso}`;
  }
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  return `${start.toLocaleDateString(undefined, opts)} – ${end.toLocaleDateString(undefined, opts)}`;
}

/** "Wed, Dec 3" for one streaming-slot day (or the as-of date). Falls back to the raw ISO string rather than throwing. */
export function formatSlotDay(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

/**
 * Which direction a "full_week" streaming plan's as_of date sits relative to
 * the week — a week already over and a week not yet started imply different
 * actions, and the backend already knows which (window_basis only says the
 * window isn't "remaining", not which side). ISO "YYYY-MM-DD" strings compare
 * correctly with plain string comparison, no Date parsing/timezone risk.
 * "unknown" covers the defensive case of missing/null week dates (see
 * formatWeekRange) — never guess a direction from data that isn't there.
 */
export function describeWindowDirection(
  asOfIso: string,
  startIso: string | null | undefined,
  endIso: string | null | undefined,
): "before" | "after" | "unknown" {
  if (!startIso || !endIso) return "unknown";
  if (asOfIso < startIso) return "before";
  if (asOfIso > endIso) return "after";
  return "unknown";
}
