import type { MatchupCategoryVerdict } from "@/lib/api";
import { LABEL_BY_CONTRACT_KEY } from "@/components/dashboard/categoryKeys";
import { formatCategoryTotal, formatMargin } from "./format";
import VerdictBadge from "./VerdictBadge";

/**
 * The close categories, ordered most-flippable-first (backend's `focus`
 * array — already ranked, never re-sorted here). This is what the add
 * schedule below is trying to move, so it comes right after the scoreboard,
 * ahead of the build profiles.
 */
export default function FocusCategories({
  focus,
  categories,
}: {
  focus: string[];
  categories: MatchupCategoryVerdict[];
}) {
  if (focus.length === 0) {
    return (
      <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
        No categories are close enough to be worth targeting this week.
      </p>
    );
  }

  const byKey = new Map(categories.map((cv) => [cv.category, cv]));

  return (
    <div>
      <p className="mb-3 text-xs text-ink/70">Ranked most flippable first.</p>
      {/* caps at 2 columns, not 3 -- this panel now sits at half page width
          (lg:grid-cols-2 on the outer page grid), so a viewport-based
          lg:grid-cols-3 here would triple the inner grid at the exact
          breakpoint the outer grid halves the available width, leaving each
          card too narrow for its label + verdict badge + mono stat line */}
      <ol className="grid gap-3 sm:grid-cols-2">
        {focus.map((key, i) => {
          const cv = byKey.get(key);
          if (!cv) return null;
          const label = LABEL_BY_CONTRACT_KEY[key] ?? key;
          return (
            <li key={key} className="border border-rule p-3">
              <p className="font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
                #{i + 1}
              </p>
              <div className="mt-1 flex items-center justify-between gap-2">
                <span className="font-display text-lg text-ink">{label}</span>
                <VerdictBadge verdict={cv.verdict} />
              </div>
              <p className="mt-1 font-mono text-xs text-ink/80">
                You {formatCategoryTotal(label, cv.mine)} · Them {formatCategoryTotal(label, cv.theirs)} ·{" "}
                {formatMargin(label, cv.margin)}
              </p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
