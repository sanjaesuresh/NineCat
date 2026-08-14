import type { CategoryKey } from "../../lib/types";

/**
 * Shared visual language for the T17 detail charts. Recharts fill/stroke
 * props take literal SVG color values, not Tailwind utility classes, so
 * these are the hex equivalents of the palette already established in
 * badges.tsx/columns.tsx (teal/rose diverging, amber accent, slate surfaces)
 * -- kept in one place so the four chart files can't drift from each other.
 */
export const CHART_COLORS = {
  teal: "#2dd4bf", // tailwind teal-400
  rose: "#fb7185", // tailwind rose-400
  amber: "#fbbf24", // tailwind amber-400, the app's accent color
  reference: "#475569", // tailwind slate-600, muted reference bars/lines
  neutralBar: "#334155", // tailwind slate-700
  grid: "#1e293b", // tailwind slate-800, matches border-slate-800
  axisText: "#94a3b8", // tailwind slate-400
} as const;

/** Canonical display order for the nine per-game z-score categories, per the
 * T17 brief -- distinct from columns.tsx's value-descending CATEGORY_ORDER,
 * which is a table-sorting concern, not a chart-reading one. */
export const ZSCORE_CATEGORY_ORDER: CategoryKey[] = [
  "fg_pct",
  "ft_pct",
  "tpm",
  "pts",
  "reb",
  "ast",
  "stl",
  "blk",
  "tov",
];

export const CATEGORY_LABELS: Record<CategoryKey, string> = {
  fg_pct: "FG%",
  ft_pct: "FT%",
  tpm: "3PM",
  pts: "PTS",
  reb: "REB",
  ast: "AST",
  stl: "ST",
  blk: "BLK",
  tov: "TO",
};

export type WeekTint = "favorable" | "unfavorable" | "neutral";

/**
 * Highlights a schedule week's game count: >=4 games is a good matchup week
 * (more counting-stat opportunities), <=2 is a bad one (bye-week-adjacent).
 * Pure + exported so both PlayerDetail's schedule rows and the PlayoffWeeks
 * chart's bar fills share one threshold definition instead of drifting.
 */
export function weekRowTint(games: number): WeekTint {
  if (games >= 4) return "favorable";
  if (games <= 2) return "unfavorable";
  return "neutral";
}

/**
 * Muted empty-state panel every chart falls back to when its source field is
 * null (e.g. schedule not yet published). Fixed height matches the real
 * chart's height so swapping between the two states doesn't jump the layout.
 * role="img" + aria-label so screen readers get "no data" instead of silence.
 */
export function ChartEmptyState({ label, height = 180 }: { label: string; height?: number }) {
  return (
    <div
      role="img"
      aria-label={`${label}: no data available`}
      style={{ height }}
      className="flex items-center justify-center rounded border border-slate-800 bg-slate-900/50 text-sm text-slate-500"
    >
      No data
    </div>
  );
}
