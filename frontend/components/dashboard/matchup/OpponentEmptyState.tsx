import type { MatchupSide, ScheduleCoverage } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { CONTRACT_KEY_BY_LABEL } from "@/components/dashboard/categoryKeys";
import { formatCategoryTotal } from "./format";
import { emptyStateClasses, noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";
import { columnHeaderClasses, numericClasses, proseClasses, subheadingClasses } from "@/components/dashboard/layout/typography";

// each reason means something different to the user — never collapse these
// into one generic "no opponent" message
const REASON_COPY: Record<string, string> = {
  yahoo_unavailable: "Yahoo's matchup data isn't reachable right now — try refreshing in a moment.",
  no_matchup_this_week:
    "There's no matchup scheduled this week (bye week, playoffs gap, or off-season).",
  no_opponent_in_matchup: "This week's matchup doesn't list an opposing team.",
  opponent_team_not_synced:
    "Your opponent hasn't synced into NineCat yet — check back after their next league sync.",
};

/**
 * Opponent-driven empty state, plus what we DO know: my own projected
 * totals, shown without a comparison the app can't make.
 *
 * `coverage` gates that totals table on its own — an opponent-less matchup
 * can ALSO have no schedule data for my own side (the dev-seed condition,
 * and any real league before its first schedule sync), and this component
 * used to print that as a confident all-zero row. It must check
 * schedule_coverage itself rather than assume the "no opponent" branch
 * means the numbers are otherwise trustworthy.
 */
export default function OpponentEmptyState({
  reason,
  mine,
  coverage,
}: {
  reason: string | null;
  mine: MatchupSide;
  coverage: ScheduleCoverage;
}) {
  const copy = (reason && REASON_COPY[reason]) ?? "No opponent could be found for this matchup.";

  return (
    <div>
      <p className={emptyStateClasses()}>{copy}</p>

      <div className="mt-4">
        <p className={subheadingClasses()}>
          {mine.name}&apos;s projected totals this week
        </p>
        {coverage.ok ? (
          // relative: keeps the sr-only caption clipped inside this scroll
          // container instead of escaping to the initial containing block.
          // tabIndex + named region: keyboard scroll access once the table
          // overflows (WCAG 2.1.1) -- see RosterTable for the full reasoning
          <div
            className="relative mt-2 overflow-x-auto border border-rule"
            tabIndex={0}
            role="region"
            aria-label={`${mine.name}'s projected category totals`}
          >
            <table className="w-full min-w-[560px] border-collapse text-left">
              <caption className="sr-only">{mine.name}&apos;s projected category totals</caption>
              <thead>
                <tr className="border-b-2 border-ink">
                  {CATEGORIES.map((cat) => (
                    <th
                      key={cat}
                      scope="col"
                      className={`whitespace-nowrap border-r border-rule px-3 py-2 text-center ${columnHeaderClasses()} last:border-r-0`}
                    >
                      {cat}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  {CATEGORIES.map((cat) => (
                    <td
                      key={cat}
                      className={`whitespace-nowrap border-r border-rule px-3 py-3 text-center ${numericClasses()} last:border-r-0`}
                    >
                      {formatCategoryTotal(cat, mine.projection.totals[CONTRACT_KEY_BY_LABEL[cat]])}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        ) : (
          <p className={`mt-2 ${noticeClasses()} ${proseClasses()}`}>
            <span className={noticeDotClasses("warn")} aria-hidden="true" />
            Schedule data is missing for this week, so those totals would show as zero — not shown
            as a real projection. This should fill in once the schedule next syncs.
          </p>
        )}
      </div>
    </div>
  );
}
