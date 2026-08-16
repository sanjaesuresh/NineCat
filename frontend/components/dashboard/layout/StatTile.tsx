import type { ReactNode } from "react";
import { statTileClasses } from "./layoutTokens";
import { captionClasses, eyebrowClasses } from "./typography";

/**
 * One glanceable number inside a StatRow grid: a small condensed label, a
 * large display-font value (the only places Anton is allowed besides page
 * titles), and an optional muted sub-line for context (e.g. a delta or
 * rank). Carries its own hairline border since StatRow's grid gap is the
 * only thing separating tiles. Value is one step below PageHeader's h1
 * (text-figure vs text-headline) so a row of tiles under a page title doesn't
 * compete with it. text-figure ships its own 1.05 leading, so the explicit
 * leading-none this used to carry is gone.
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
      {/* one of the two sanctioned homes for uppercase (the other is short
          badges) -- a tile label is two or three words and reads as a legend */}
      <p className={eyebrowClasses()}>{label}</p>
      <p className="mt-1.5 font-display text-figure text-ink">{value}</p>
      {sub && <p className={`mt-1.5 ${captionClasses()}`}>{sub}</p>}
    </div>
  );
}
