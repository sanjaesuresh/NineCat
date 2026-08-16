/**
 * Pure Tailwind class-string helpers for the dashboard's shared layout
 * primitives (Panel, StatRow, StatTile, table rows). Kept dependency-free so
 * they are cheap to unit-test with plain substring assertions -- no DOM, no
 * React. Consumers (components/dashboard/layout/Panel.tsx, StatRow.tsx,
 * StatTile.tsx, and the existing table components) call these instead of
 * hand-writing class strings so the density/border/background choices stay
 * in one place.
 */

type PanelTone = "default" | "destructive";

type PanelOptions = {
  /** True for a panel that should not carry its own inner padding, e.g. one
   * whose child already manages spacing (a table that wants to run its rows
   * flush to the panel's border). */
  flush?: boolean;
  /** "default" (the usual hairline border) or "destructive" (the alert-red
   * border for irreversible actions, e.g. Settings' delete-account panel).
   * A tone rather than a raw className override: panelClasses returns
   * exactly one border-color class per call, so a caller never needs
   * `!important` to make a destructive border win the cascade. */
  tone?: PanelTone;
};

// --panel is the committed section backdrop; --rule is globals.css's
// documented translucent 24% hairline token (used here as a divider, not as
// text -- it is not on the TEXT-SAFE list) and --alert is the only
// text/border-safe destructive token, per that same list.
const PANEL_BORDER: Record<PanelTone, string> = {
  default: "border-rule",
  destructive: "border-alert",
};
// 20px, up from 16px: the type scale raised the floor to 13px and gave panel
// titles 18px, so the old inset left the content crowding its own border
const PANEL_PADDING = "p-5";

/** Container classes for the dashboard's Panel primitive. */
export function panelClasses(options: PanelOptions = {}): string {
  const { flush = false, tone = "default" } = options;
  const base = `border ${PANEL_BORDER[tone]} bg-panel`;
  return flush ? base : `${base} ${PANEL_PADDING}`;
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

/**
 * The page-level content stack under PageHeader, shared by all six dashboard
 * tabs (previously the same literal hand-written on each page). mt-3 against
 * the stack's own space-y-4 is the one deliberate rung of rhythm variation:
 * the summary tile row hugs the header it summarizes slightly tighter than
 * panels sit from each other, instead of the flagged uniform 16px everywhere.
 */
export function pageStackClasses(): string {
  return "mt-3 space-y-4 px-6 sm:px-10";
}

// shared project-wide table row height -- h-11 is Tailwind's standard scale
// utility that equals 44px, so it scales with the user's root font size.
// Raised from h-9/36px with the type scale: 14px data text needs the room,
// and rows carrying interactive content then clear WCAG 2.2 2.5.8's pointer
// target for free. This is a MINIMUM, not a fixed height -- measurement
// showed real rows already ranging 32.5px to 77px depending on whether a
// cell wraps, so treating the old 36px as a guarantee was always a fiction.
const TABLE_ROW_HEIGHT = "h-11";

// --rule is globals.css's documented translucent 24% hairline token, used
// here as a divider, not as text -- zebra striping was removed because no
// --paper-*/--panel pairing in this palette clears 1.1:1 contrast, so it
// read as invisible
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
const STAT_TILE_BASE = "border border-rule p-5";

/** Container classes for the dashboard's StatTile primitive. */
export function statTileClasses(): string {
  return STAT_TILE_BASE;
}

type NoticeTone = "info" | "warn" | "error";

// tone never touches the container: every notice shares the same hairline box
// (border-rule, like panelClasses -- exactly one border-colour class per call)
// and severity is carried by the leading dot instead. This replaced the
// border-l-4 side-stripe, where warn/error/info differed only by stripe hue.
const NOTICE_DOT: Record<NoticeTone, string> = {
  info: "bg-court",
  warn: "bg-amber",
  error: "bg-alert",
};

/**
 * Container classes for an inline notice (stale banner, error strip, ranking
 * caveat). Flex so the tone dot from noticeDotClasses sits beside the copy;
 * padding is baked in (same trade-off as panelClasses -- callers do not add
 * their own). Pair with a `role="alert"` / `role="status"` at the call site;
 * the role is the a11y contract, this is only the box.
 */
export function noticeClasses(): string {
  return "flex items-start gap-2.5 border border-rule bg-wash px-4 py-3";
}

/**
 * The notice's leading tone dot -- the same dot vocabulary InjuryBadge,
 * VerdictBadge and StaleBanner's chip already use, so colour never carries
 * meaning alone (the copy does). mt-2 optically centres the 6px dot on the
 * first prose line; render with aria-hidden, the dot is decoration.
 */
export function noticeDotClasses(tone: NoticeTone): string {
  return `mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${NOTICE_DOT[tone]}`;
}

/**
 * The one motion recipe for anything clickable: colour transitions only, at
 * the landing chrome's 150ms + --ease-out-quart (Hero.tsx), so dashboard
 * controls and marketing CTAs settle identically instead of splitting between
 * Tailwind's stock ease and ad-hoc duration-200s. Lives here rather than in
 * typography.ts because that module's contract is type only; controlClasses
 * composes this in so a control cannot forget it, and clickables that can't
 * use controlClasses (inverted CTAs, link cards) call it directly.
 *
 * The press state rides along here for the same cannot-forget reason. A
 * brightness dip rather than a translate (no bouncy-UI movement) and rather
 * than a fixed active colour: these controls hover into different fills
 * (ink, alert, court), so only a hue-preserving dim reads as "one step
 * further" on all of them -- and on touch, where hover never fires, it is
 * the only press acknowledgement at all.
 */
export function controlMotionClasses(): string {
  return "transition-colors duration-150 ease-[var(--ease-out-quart)] active:brightness-75";
}

/**
 * The dashed "nothing to show here" box, which was hand-written identically in
 * 17 places. Carries its own type (rather than deferring to typography.ts's
 * proseClasses) because the measure has to be centred here: proseClasses caps
 * the line length and leaves the block left-aligned, which reads as
 * off-centre inside a full-width panel. `mx-auto` plus the same 68ch cap
 * centres the whole text column instead.
 */
export function emptyStateClasses(): string {
  return "mx-auto max-w-[68ch] border border-dashed border-rule px-5 py-6 text-center font-body text-prose text-ink-muted";
}
