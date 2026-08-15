/**
 * Pure Tailwind class-string helpers for the dashboard's shared layout
 * primitives (Panel, StatRow, StatTile, table rows). Kept dependency-free so
 * they are cheap to unit-test with plain substring assertions -- no DOM, no
 * React. Consumers (components/dashboard/layout/Panel.tsx, StatRow.tsx,
 * StatTile.tsx, and the existing table components) call these instead of
 * hand-writing class strings so the density/border/background choices stay
 * in one place.
 */

type PanelOptions = {
  /** True for a panel that should not carry its own inner padding, e.g. one
   * whose child already manages spacing (a table that wants to run its rows
   * flush to the panel's border). */
  flush?: boolean;
};

// --panel is the committed section backdrop and --rule is the only
// text/border-safe hairline token -- see globals.css's TEXT-SAFE list.
const PANEL_BASE = "border border-rule bg-panel";
const PANEL_PADDING = "p-4";

/** Container classes for the dashboard's Panel primitive. */
export function panelClasses(options: PanelOptions = {}): string {
  const { flush = false } = options;
  return flush ? PANEL_BASE : `${PANEL_BASE} ${PANEL_PADDING}`;
}

/**
 * Turns a panel's title into its default heading id, e.g. "Focus Categories"
 * -> "panel-focus-categories". Deterministic (not React's useId, which is
 * stable per-render but not per-title, and would vary across builds), so the
 * same title always yields the same id -- e2e specs target these ids
 * directly (see Panel.tsx's `headingId` prop), so the format here is a
 * public contract, not an implementation detail.
 *
 * Titles that differ only in punctuation collide, e.g. "Punt Build" and
 * "Punt, Build" both slugify to "panel-punt-build". That is acceptable: a
 * caller that needs a distinct or stable id (matching an existing e2e
 * locator, or disambiguating a collision) passes Panel's `headingId` prop to
 * override this default outright.
 */
export function panelHeadingId(title: string): string {
  const slug = title
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `panel-${slug}`;
}

/**
 * Grid classes for the dashboard's StatRow primitive. Two columns at base
 * width always; once there are three or more tiles, widen to four columns
 * at the large breakpoint rather than leaving a lonely third tile stranded
 * in a 2-column grid.
 */
export function statRowClasses(tileCount: number): string {
  const base = "grid grid-cols-2 gap-3";
  return tileCount >= 3 ? `${base} lg:grid-cols-4` : base;
}

// fixed project-wide table row height -- h-9 is Tailwind's standard scale
// utility that equals 36px (matches PlayerAvatar.tsx's h-9), not an
// arbitrary value, so it scales with the user's root font size
const TABLE_ROW_HEIGHT = "h-9";

// --rule is the only text/border-safe hairline token (see globals.css's
// TEXT-SAFE list) -- zebra striping was removed because no --paper-*/--panel
// pairing in this palette clears 1.1:1 contrast, so it read as invisible
const ROW_SEPARATOR = "border-b border-rule";

type TableRowOptions = {
  /** Total number of rows being rendered, so the last row can omit its
   * separator. Required (not optional/defaulted) because a caller that
   * forgets to pass it would otherwise silently draw a separator under
   * the final row. */
  rowCount: number;
};

/**
 * Classes for one table row, zero-based `index`. Every row gets the fixed
 * 36px height; every row except the last (determined from `rowCount`, since
 * that can't be derived from `index` alone) draws a bottom hairline
 * separator. No row carries a background colour.
 */
export function tableRowClasses(
  index: number,
  { rowCount }: TableRowOptions,
): string {
  const isLast = index === rowCount - 1;
  const separator = isLast ? "" : ROW_SEPARATOR;
  return [TABLE_ROW_HEIGHT, separator].filter(Boolean).join(" ");
}

// same hairline/padding pair as PANEL_BASE/PANEL_PADDING -- kept as its own
// constant rather than reused from those two so StatTile's border+padding
// can change independently of Panel's without an accidental coupling
const STAT_TILE_BASE = "border border-rule p-4";

/** Container classes for the dashboard's StatTile primitive. */
export function statTileClasses(): string {
  return STAT_TILE_BASE;
}
