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

  if (typeof value === "number") {
    if (!Number.isFinite(value)) return EM_DASH;
    if (PERCENT_CATEGORIES.has(category)) {
      // ratio (<=1) vs already-percent (>1): scale only the ratio form so both
      // conventions render as a normal percentage instead of "0.5%" or "4520%"
      const percent = Math.abs(value) <= 1 ? value * 100 : value;
      return `${percent.toFixed(1)}%`;
    }
    return value.toFixed(1);
  }

  // backend may already send a formatted string (e.g. "45.2%") — pass it through
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

/** Normalizes a backend build-profile label into the three tones the strip renders. */
export function classifyBuildLabel(label: unknown): BuildTone {
  if (typeof label !== "string") return "average";
  const normalized = label.trim().toLowerCase();
  if (normalized.includes("strong")) return "strong";
  if (normalized.includes("punt")) return "punt";
  return "average";
}
