import { categoryLabelOrGap } from "@/components/dashboard/categoryKeys";
import { describeOpponentReason } from "./tokens";
import { eyebrowClasses, proseClasses } from "@/components/dashboard/layout/typography";
import { noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";

/**
 * Tells the user what this ranking is actually optimizing for -- the single
 * most important honesty surface on this page (docs/waiver-valuation-plan.md
 * W1/risks: "this feature is only as good as the Matchup Monitor's
 * close-category verdicts... the page should show which categories it is
 * optimising for so the user can sanity-check the premise").
 *
 * Two distinct cases, never collapsed into one generic line:
 *  - opponent_reason set: no opponent could be identified this week, so the
 *    backend degraded to roster-need-only scoring (see
 *    score_waiver_candidates -- close_categories is empty in this case, but
 *    that's a CONSEQUENCE of the fallback, not the message itself).
 *  - opponent_reason null: a real opponent was found. close_categories may
 *    still be empty (nothing in the matchup is close right now) -- that's
 *    also need-only ranking, but for a different, non-error reason.
 */
export default function RankingBasis({
  closeCategories,
  opponentReason,
}: {
  closeCategories: string[];
  opponentReason: string | null;
}) {
  if (opponentReason) {
    return (
      <div role="status" className={noticeClasses()}>
        <span className={noticeDotClasses("warn")} aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-ink">
            Ranking by roster need only — no opponent could be identified this week, so this list
            isn&apos;t weighted toward a specific matchup.
          </p>
          <p className={`mt-1 ${proseClasses("muted")}`}>{describeOpponentReason(opponentReason)}</p>
        </div>
      </div>
    );
  }

  if (closeCategories.length === 0) {
    // deliberately NOT the dashed centred box: that motif means "there is
    // nothing here", and this is a statement about how a populated list was
    // ranked, not an empty state
    return (
      <p className="text-ink">
        No categories in this week&apos;s matchup are close enough to target — ranking by roster
        need alone.
      </p>
    );
  }

  return (
    <div>
      <p className={proseClasses("muted")}>Targeting the categories close in this week&apos;s matchup:</p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {closeCategories.map((key) => (
          <li
            key={key}
            className={`border border-rule px-2 py-1 ${eyebrowClasses("ink")}`}
          >
            {categoryLabelOrGap(key)}
          </li>
        ))}
      </ul>
    </div>
  );
}
