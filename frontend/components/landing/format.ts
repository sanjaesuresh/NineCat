// shared stat-sheet formatters — mirror the approved mockup's pct()/num() helpers
// exactly, so the hero's build table and the trade ledger's swing grid can't drift
// on formatting (design review finding E2). Percentages print without the leading
// zero (".569", not "0.569"); counting stats print to one decimal.

/** fg%/ft%-style values — three decimals, no leading zero. */
export function formatPct(value: number): string {
  return value.toFixed(3).replace(/^0/, "");
}

/** counting stats (pts, reb, ast, stl, blk, 3pm, to) — one decimal. */
export function formatCounting(value: number): string {
  return value.toFixed(1);
}
