import type { MatchupSide, MatchupComparisonResult } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { CONTRACT_KEY_BY_LABEL } from "@/components/dashboard/categoryKeys";
import VerdictBadge from "./VerdictBadge";
import { formatCategoryTotal } from "./format";
import { captionClasses, columnHeaderClasses, eyebrowClasses, numericClasses, subheadingClasses, uiTextClasses } from "@/components/dashboard/layout/typography";

/**
 * The headline of the page — both sides' projected category totals plus the
 * per-category verdict and the projected score line. Deliberately one row
 * per CATEGORY (not one row per team, the RosterTable/MatchupStrip
 * convention) since there are only two numeric columns to compare here; a
 * 9-column team-per-row table would force horizontal scrolling for no
 * benefit and bury the thing the user is actually scanning for — who's
 * ahead in what.
 */
export default function ProjectedScoreboard({
  mine,
  opponent,
  comparison,
}: {
  mine: MatchupSide;
  opponent: MatchupSide;
  comparison: MatchupComparisonResult;
}) {
  const [mineWins, theirWins] = comparison.projected_score;
  const byCategory = new Map(comparison.categories.map((cv) => [cv.category, cv]));

  return (
    <div>
      <div className="mb-4">
        <p className={eyebrowClasses()}>
          Projected category score
        </p>
        {/* team names are small mono labels, the digits are the only large
            display element — a single combined sentence ("Team A 6–3 Team B")
            let two real Yahoo team names wrap at 360px and split the score
            itself across lines. Each side is its own block instead, so a
            long name wraps within its own label without ever touching the
            digits below it. */}
        <div
          role="group"
          aria-label="Projected category score"
          className="mt-2 flex flex-wrap items-end gap-x-6 gap-y-2"
        >
          <div className="min-w-0">
            <p className={`max-w-[9rem] ${subheadingClasses("muted")}`}>
              {mine.name}
            </p>
            <p className="font-display text-5xl text-ink">{mineWins}</p>
          </div>
          <span className="sr-only">to</span>
          <p aria-hidden="true" className="font-display text-figure text-ink-muted">
            –
          </p>
          <div className="min-w-0">
            <p className={`max-w-[9rem] ${subheadingClasses("muted")}`}>
              {opponent.name}
            </p>
            <p className="font-display text-5xl text-ink">{theirWins}</p>
          </div>
        </div>
        <p className={`mt-2 ${captionClasses()}`}>
          Categories the week&apos;s projection favors; a tied category counts to neither side.
        </p>
      </div>

      {/* relative: keeps the sr-only caption clipped inside this scroll
          container instead of escaping to the initial containing block.
          tabIndex + named region: keyboard scroll access once the table
          overflows (WCAG 2.1.1) -- see RosterTable for the full reasoning */}
      <div
        className="relative overflow-x-auto border border-rule"
        tabIndex={0}
        role="region"
        aria-label={`Projected category totals, ${mine.name} versus ${opponent.name}`}
      >
        <table className="w-full min-w-[420px] border-collapse text-left">
          <caption className="sr-only">
            Projected category totals, {mine.name} versus {opponent.name}
          </caption>
          <thead>
            <tr className="border-b-2 border-ink">
              <th
                scope="col"
                className={`px-3 py-2 ${columnHeaderClasses()}`}
              >
                Category
              </th>
              <th
                scope="col"
                className={`border-l border-rule px-3 py-2 text-right ${columnHeaderClasses()}`}
              >
                {mine.name}
              </th>
              <th
                scope="col"
                className={`border-l border-rule px-3 py-2 text-right ${columnHeaderClasses()}`}
              >
                {opponent.name}
              </th>
              <th
                scope="col"
                className={`border-l border-rule px-3 py-2 ${columnHeaderClasses()}`}
              >
                Result
              </th>
            </tr>
          </thead>
          <tbody>
            {CATEGORIES.map((label) => {
              const key = CONTRACT_KEY_BY_LABEL[label];
              const cv = byCategory.get(key);
              return (
                <tr key={label} className="border-b border-rule last:border-b-0">
                  <td className={`px-3 py-2 ${uiTextClasses("muted")}`}>{label}</td>
                  <td className={`border-l border-rule px-3 py-2 text-right ${numericClasses()}`}>
                    {cv ? formatCategoryTotal(label, cv.mine) : "—"}
                  </td>
                  <td className={`border-l border-rule px-3 py-2 text-right ${numericClasses()}`}>
                    {cv ? formatCategoryTotal(label, cv.theirs) : "—"}
                  </td>
                  <td className="border-l border-rule px-3 py-2">
                    <VerdictBadge verdict={cv?.verdict} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
