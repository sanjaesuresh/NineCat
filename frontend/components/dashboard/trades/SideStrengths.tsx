import type { TradePlayerInfo, TradeSide } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { CONTRACT_KEY_BY_LABEL } from "@/components/dashboard/categoryKeys";
import { classifyBuildLabel, formatZScore } from "@/components/dashboard/format";
import { columnHeaderClasses, numericClasses, uiTextClasses } from "@/components/dashboard/layout/typography";

const TONE_TEXT = { strong: "Strong", average: "Average", punt: "Punt" } as const;

/**
 * One side's nine categories with the two signals that decide what can
 * actually be traded: DEPTH (how many rostered players meaningfully
 * contribute) and FRAGILE (strong only because of one dominant contributor).
 *
 * Fragility is given its own column rather than a footnote because it is the
 * whole reason the depth analysis exists -- a category that is strong on one
 * player's back is not surplus, and trading that player collapses it instead
 * of merely weakening it (docs/trade-analyzer-plan.md T1). Surplus already
 * excludes fragile categories on the backend, so the two columns together
 * explain why a strong category is missing from the tradeable list.
 */
export default function SideStrengths({
  side,
  players,
}: {
  side: TradeSide;
  players: Record<string, TradePlayerInfo>;
}) {
  const surplus = new Set(side.surplus);
  const deficit = new Set(side.deficit);

  // tabIndex + named region: keyboard scroll access once the table overflows
  // (WCAG 2.1.1) -- see RosterTable for the full reasoning. aria-label rather
  // than a caption id because the trades page mounts one of these per side
  const caption = "Category strengths, depth and fragility for this roster";
  return (
    <div
      className="relative overflow-x-auto border border-rule"
      tabIndex={0}
      role="region"
      aria-label={caption}
    >
      {/* min-w kept modest deliberately: these two tables stack in one column
          (see the page) precisely because side-by-side at this width forces a
          horizontal scroll on an ordinary desktop */}
      <table className="w-full min-w-[440px] border-collapse text-left">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b-2 border-ink">
            {["Cat", "Build", "Mean z", "Depth", "Top share", "Trade role"].map((heading) => (
              <th
                key={heading}
                scope="col"
                className={`whitespace-nowrap px-3 py-2 ${columnHeaderClasses()}`}
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {CATEGORIES.map((label) => {
            const key = CONTRACT_KEY_BY_LABEL[label];
            const strength = side.categories[key];
            const tone = classifyBuildLabel(strength?.label);
            const topName = strength?.top_contributor
              ? (players[strength.top_contributor]?.name ?? "—")
              : "—";
            return (
              <tr key={label} className="border-b border-rule last:border-b-0">
                <th
                  scope="row"
                  className={`whitespace-nowrap px-3 py-2 text-left ${uiTextClasses()}`}
                >
                  {label}
                </th>
                <td className={`whitespace-nowrap px-3 py-2 ${uiTextClasses()}`}>
                  {tone === null ? "No data" : TONE_TEXT[tone]}
                </td>
                <td className={`whitespace-nowrap px-3 py-2 ${numericClasses("muted")}`}>
                  {formatZScore(strength?.mean)}
                </td>
                <td className={`whitespace-nowrap px-3 py-2 ${numericClasses("muted")}`}>
                  {strength?.depth ?? "—"}
                </td>
                <td className={`whitespace-nowrap px-3 py-2 ${uiTextClasses("muted")}`}>
                  {topName}
                  {strength ? ` (${Math.round(strength.top_share * 100)}%)` : ""}
                </td>
                <td className={`px-3 py-2 ${uiTextClasses()}`}>
                  {surplus.has(key) ? (
                    "Tradeable surplus"
                  ) : strength?.fragile ? (
                    <span className="text-ink">
                      Fragile — strong on one player, not tradeable
                    </span>
                  ) : deficit.has(key) ? (
                    "Needs help"
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
