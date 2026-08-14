// Adds-page-specific number formatting. games_remaining and category totals
// reuse the shared dashboard/format.ts and matchup/format.ts helpers
// (formatGamesCount, formatWeekRange, formatSlotDay, describeWindowDirection)
// -- this file only adds the one thing neither already covers.

const EM_DASH = "—";

/**
 * A candidate's waiver score. Unlike draft board value (which can be
 * negative, so it always shows a sign), every candidate on this page has
 * already cleared engine.contribution.is_worth_it (score > 0) -- a
 * forced "+" on a number that's always positive would just be noise, so
 * this omits the sign formatSignedNumber applies elsewhere. Still
 * integer-safe (never "5.00" when the value happens to land on a whole
 * number) per the same convention as formatGamesCount/formatCategoryTotal.
 */
export function formatWaiverScore(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return EM_DASH;
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}
