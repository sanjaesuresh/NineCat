import { CATEGORIES } from "./categories";

/**
 * The page's signature motif: a real box-score row for the 9 standard
 * head-to-head categories. "full" renders it as an actual <table> (the
 * hero's centerpiece — literally what NineCat tracks). "chips" renders the
 * same 9 abbreviations as small inline tokens for reuse in tighter spots.
 */
export default function CategoryLedger({
  variant = "full",
}: {
  variant?: "full" | "chips";
}) {
  if (variant === "chips") {
    return (
      <ul className="flex flex-wrap gap-x-3 gap-y-1.5" aria-label="The 9 scoring categories">
        {CATEGORIES.map((cat) => (
          <li
            key={cat}
            className="font-mono text-xs tracking-wide text-ink/70 before:content-['·'] before:mr-3 before:text-rule first:before:content-none"
          >
            {cat}
          </li>
        ))}
      </ul>
    );
  }

  return (
    // no min-width here on purpose: at 9 columns, a fixed min-width wider
    // than the narrowest container (mobile, ~312px content box) clips the
    // last column instead of shrinking. cell padding/font are tuned so the
    // table's natural width fits down to 320px without wrapping or clipping;
    // overflow-x-auto is a defensive fallback only, not the sizing strategy.
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <caption className="mb-2 text-left font-mono text-xs uppercase tracking-[0.15em] text-ink/70">
          All 9 categories, every week
        </caption>
        <thead>
          <tr className="border-b-2 border-ink">
            {CATEGORIES.map((cat) => (
              <th
                key={cat}
                scope="col"
                className="whitespace-nowrap border-r border-rule px-1 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70 last:border-r-0"
              >
                {cat}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-rule">
            {CATEGORIES.map((cat) => (
              <td
                key={cat}
                className="whitespace-nowrap border-r border-rule px-1 py-3 text-center font-mono text-court last:border-r-0"
                aria-label={`${cat}: tracked`}
              >
                ●
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
