/**
 * Pure Tailwind class-string helpers for the dashboard's text roles, built on
 * the named type scale in app/globals.css (--text-headline, --text-section,
 * --text-prose, --text-ui, --text-data, --text-caption, --text-eyebrow, ...).
 * Same shape and testing story as layoutTokens.ts in this directory: no DOM,
 * no React, cheap to assert on with plain substring checks.
 *
 * Division of labour with layoutTokens.ts: that module owns geometry (panel
 * and tile containers, table row height, separators), this one owns type
 * (family, size, case, colour). A table cell therefore gets its padding and
 * alignment written at the call site and its type from here.
 *
 * Padding is deliberately NOT baked into these strings. Tailwind here has no
 * class-merging utility (and this project may not add one), so a returned
 * "px-3 py-2" that a caller needed to override would produce two competing
 * padding classes resolved by stylesheet order, not by call-site order -- a
 * silent, hard-to-spot bug. Keeping padding at the call site means an
 * override is just a different literal.
 *
 * Only --ink and --ink-muted appear here. The dashboard previously carried
 * 149 opacity-modified inks across five undeclared levels (text-ink/70, /80,
 * /90, /60, /25) against 6 uses of the named muted token, which is why
 * secondary text read as faded rather than deliberate. Both tokens below are
 * on globals.css's TEXT-SAFE list; the opacity ladder was not measured.
 */

import { controlMotionClasses } from "./layoutTokens";

/** Two text colours, no third: full-contrast ink, or the muted secondary. */
type Tone = "ink" | "muted";

const TONE_CLASS: Record<Tone, string> = {
  ink: "text-ink",
  muted: "text-ink-muted",
};

/**
 * Panel and section titles. Sentence case on purpose -- these used to be 12px
 * uppercase mono, which is why hierarchy had to be carried by colour; at 18px
 * condensed a title can simply look like a title.
 */
export function headingClasses(tone: Tone = "ink"): string {
  return `font-condensed text-section font-semibold ${TONE_CLASS[tone]}`;
}

/**
 * A heading nested inside a Panel: an `<h3>`, or a `<caption>` naming a table
 * that already sits under a panel title. Deliberately 15px against the panel
 * title's 18px -- close enough to read as the same family of thing, far
 * enough that the two don't compete for the same rung.
 */
export function subheadingClasses(tone: Tone = "ink"): string {
  return `font-condensed text-prose font-semibold ${TONE_CLASS[tone]}`;
}

/**
 * The uppercase accent: stat-tile labels and short badges (INJ, SZN AVG,
 * verdict pills). --text-eyebrow is the only scale step carrying letter
 * spacing, so this is the single sanctioned home for uppercase + tracking.
 * Anything longer than about three words does not belong here.
 */
export function eyebrowClasses(tone: Tone = "muted"): string {
  return `font-condensed text-eyebrow font-semibold uppercase ${TONE_CLASS[tone]}`;
}

/**
 * Table column headers. Sets font-weight explicitly rather than leaving the
 * browser's bold `<th>` default in place -- that default is what all 37 of
 * the old `font-normal` overrides existed to cancel.
 */
export function columnHeaderClasses(): string {
  return "font-condensed text-caption font-semibold text-ink-muted";
}

/**
 * Numeric table cells and stat digits -- the only sanctioned use of Space
 * Mono, per the rule already stated in app/layout.tsx. tabular-nums is part
 * of the recipe, not optional: monospace alone does not guarantee lining
 * figures, and aligned digits are the entire justification for the face.
 */
export function numericClasses(tone: Tone = "ink"): string {
  return `font-mono text-data tabular-nums ${TONE_CLASS[tone]}`;
}

/** Dense UI text: nav, form controls, and non-numeric table cells. */
export function uiTextClasses(tone: Tone = "ink"): string {
  return `font-body text-ui ${TONE_CLASS[tone]}`;
}

/**
 * Running prose: notices, explanations, empty states. Capped at a 68-character
 * measure so a sentence cannot run the full width of a 1600px page -- an
 * uncapped line length on a wide dashboard is a large part of what reads as
 * "developer text" even after the face is fixed.
 */
export function proseClasses(tone: Tone = "ink"): string {
  return `max-w-[68ch] font-body text-prose ${TONE_CLASS[tone]}`;
}

/** Sub-lines and meta: a stat tile's delta, a timestamp, a footnote. */
export function captionClasses(tone: Tone = "muted"): string {
  return `font-body text-caption ${TONE_CLASS[tone]}`;
}

/**
 * Button and control labels. Sentence case, unlike the site chrome's
 * uppercase masthead CTAs: the chrome is a masthead and can shout, an inline
 * dashboard control should not. Returns type plus the shared motion recipe
 * (controlMotionClasses -- baked in here because per-site transition classes
 * are how 12 bare `transition-colors` accumulated); borders, hover and
 * disabled states stay at the call site.
 */
export function controlClasses(tone: Tone = "ink"): string {
  return `font-condensed text-ui font-semibold ${controlMotionClasses()} ${TONE_CLASS[tone]}`;
}
