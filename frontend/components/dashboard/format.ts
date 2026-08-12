// Presentation-only helpers shared by the dashboard's box-score tables.
// Every API field here is typed `unknown` in lib/api.ts on purpose (the backend
// contract isn't locked yet), so these helpers must degrade to an em-dash rather
// than throw on a shape they don't recognize.

const EM_DASH = "—";

/** Percentage categories may arrive as a 0-1 ratio or an already-scaled percent. */
const PERCENT_CATEGORIES = new Set(["FG%", "FT%"]);

/** Formats one player/team stat cell. Never throws — unknown shapes fall back to an em-dash. */
export function formatStatValue(category: string, value: unknown): string {
  if (value === null || value === undefined) return EM_DASH;

  // matchup category_totals arrive as JSON strings ("0.471") even when the
  // underlying value is numeric, while roster averages arrive as real numbers
  // — coerce numeric-looking strings first so both sources format identically
  // (e.g. "48.2%") instead of one leaking the raw decimal string through
  let numeric: number | null = null;
  if (typeof value === "number") {
    numeric = value;
  } else if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    numeric = Number(value);
  }

  if (numeric !== null) {
    if (!Number.isFinite(numeric)) return EM_DASH;
    if (PERCENT_CATEGORIES.has(category)) {
      // ratio (<=1) vs already-percent (>1): scale only the ratio form so both
      // conventions render as a normal percentage instead of "0.5%" or "4520%"
      const percent = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
      return `${percent.toFixed(1)}%`;
    }
    return numeric.toFixed(1);
  }

  // backend may already send a non-numeric formatted string (e.g. "Q1") — pass it through
  if (typeof value === "string" && value.trim() !== "") return value;

  return EM_DASH;
}

/** Formats an ISO timestamp for the "last synced" reads. Never throws on a bad string. */
export function formatSyncedAt(iso: string | null): string {
  if (!iso) return "never";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "unknown time";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export type InjuryTone = "alert" | "amber";

export interface InjuryDisplay {
  label: string;
  tone: InjuryTone;
}

/** Maps a raw Yahoo injury code to a badge tone. Unknown codes still render (amber, cautious default). */
export function classifyInjury(status: string | null): InjuryDisplay | null {
  if (!status || !status.trim()) return null;
  const code = status.trim().toUpperCase();
  // "out" and general "injured" are the only codes that mean zero availability
  const outTones = new Set(["O", "OUT", "INJ", "IL", "IR"]);
  return { label: code, tone: outTones.has(code) ? "alert" : "amber" };
}

export type BuildTone = "strong" | "punt" | "average";

const BUILD_TONES = new Set<BuildTone>(["strong", "punt", "average"]);

/**
 * Normalizes a backend build-profile label into one of the three known tones.
 * Returns null for anything else (missing, empty, or an unrecognized string) —
 * an unclassified category must render as an explicit no-data cell, never
 * silently default to "average" and pretend it was classified.
 */
export function classifyBuildLabel(label: unknown): BuildTone | null {
  if (typeof label !== "string") return null;
  const normalized = label.trim().toLowerCase();
  return BUILD_TONES.has(normalized as BuildTone) ? (normalized as BuildTone) : null;
}

/**
 * Signs and formats a mean z-score for the build-profile strip (e.g. "+0.42 z",
 * "−0.11 z"). Deliberately separate from formatStatValue, which applies a
 * percent heuristic that doesn't apply to z-scores at all.
 */
export function formatZScore(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return EM_DASH;
  const sign = value < 0 ? "−" : "+"; // U+2212 minus sign, not a hyphen
  return `${sign}${Math.abs(value).toFixed(2)} z`;
}
