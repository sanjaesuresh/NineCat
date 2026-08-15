import type { ReactNode } from "react";
import { statTileClasses } from "./layoutTokens";

/**
 * One glanceable number inside a StatRow grid: a small condensed label, a
 * large display-font value (the only places Anton is allowed besides page
 * titles), and an optional muted sub-line for context (e.g. a delta or
 * rank). Carries its own hairline border since StatRow's grid gap is the
 * only thing separating tiles. Value is one step below PageHeader's h1
 * (text-2xl vs text-3xl, matching ProjectedScoreboard's secondary display
 * number) so a row of tiles under a page title doesn't compete with it.
 */
export default function StatTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
}) {
  return (
    <div className={statTileClasses()}>
      <p className="font-condensed text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 font-display text-2xl leading-none text-ink">{value}</p>
      {sub && <p className="mt-1 text-xs text-ink-muted">{sub}</p>}
    </div>
  );
}
