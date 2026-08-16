import type { Matchup } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { formatStatValue } from "./format";
import { STAT_ID_BY_LABEL } from "./categoryKeys";
import { columnHeaderClasses, numericClasses, subheadingClasses, uiTextClasses } from "@/components/dashboard/layout/typography";
import { emptyStateClasses } from "@/components/dashboard/layout/layoutTokens";

export default function MatchupStrip({ matchup }: { matchup: Matchup | null }) {
  if (!matchup) {
    return (
      <div className={emptyStateClasses()}>
        <p>No matchup this week.</p>
        <p className={`mt-1 ${uiTextClasses("muted")}`}>
          This is normal in the offseason or during a league bye.
        </p>
      </div>
    );
  }

  // relative: keeps absolutely-positioned sr-only children clipped inside this
  // scroll container instead of escaping to the initial containing block
  // tabIndex + named region: keyboard scroll access once the table overflows
  // (WCAG 2.1.1) -- see RosterTable for the full reasoning
  const caption = `Week ${matchup.week} matchup`;
  return (
    <div
      className="relative overflow-x-auto border border-rule"
      tabIndex={0}
      role="region"
      aria-label={caption}
    >
      <table className="w-full border-collapse text-left">
        <caption className={`px-3 py-2 text-left ${subheadingClasses()}`}>
          {caption}
        </caption>
        <thead>
          <tr className="border-b-2 border-ink">
            <th scope="col" className={`px-3 py-2 ${columnHeaderClasses()}`}>
              Team
            </th>
            {CATEGORIES.map((cat) => (
              <th
                key={cat}
                scope="col"
                className={`whitespace-nowrap border-l border-rule px-3 py-2 text-center ${columnHeaderClasses()}`}
              >
                {cat}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matchup.teams.map((team) => (
            <tr key={team.name} className="border-b border-rule last:border-b-0">
              <td className="px-3 py-2 text-ink">{team.name}</td>
              {CATEGORIES.map((cat) => (
                <td
                  key={cat}
                  className={`whitespace-nowrap border-l border-rule px-3 py-2 text-center ${numericClasses()}`}
                >
                  {/* category_totals is keyed by Yahoo stat id (JSON string), not the display label */}
                  {formatStatValue(cat, team.category_totals?.[STAT_ID_BY_LABEL[cat]])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
