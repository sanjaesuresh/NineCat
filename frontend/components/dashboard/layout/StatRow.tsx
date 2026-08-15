import { Children, type ReactNode } from "react";
import { statRowClasses } from "./layoutTokens";

/**
 * Responsive grid for a row of StatTiles. Counts children with
 * Children.toArray (not Children.count, which counts null/undefined/boolean
 * nodes -- e.g. a conditionally-rendered tile that evaluates to `false` --
 * as real children, inflating the count and tripping statRowClasses into
 * the wrong column width) so statRowClasses only widens to 4 columns once
 * there are genuinely 3+ rendered tiles. Note a Fragment child still counts
 * as one child here, same as toArray's normal behaviour -- if a caller ever
 * wraps multiple tiles in a Fragment this count won't see through it.
 * Children render directly inside the grid -- no per-child wrapper -- so CSS
 * grid placement isn't broken by an extra div.
 */
export default function StatRow({ children }: { children: ReactNode }) {
  const tileCount = Children.toArray(children).length;
  return <div className={statRowClasses(tileCount)}>{children}</div>;
}
