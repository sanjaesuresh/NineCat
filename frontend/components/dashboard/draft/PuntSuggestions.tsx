import type { DraftPuntSuggestion } from "@/lib/api";
import { LABEL_BY_CONTRACT_KEY } from "@/components/dashboard/categoryKeys";
import { formatZScore } from "@/components/dashboard/format";
import { captionClasses, proseClasses, subheadingClasses } from "@/components/dashboard/layout/typography";
import { controlMotionClasses, emptyStateClasses, noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";

// canonical-order arrays compare by value, not by reference/order, since
// both `applied`/`pendingPunt` and each suggestion's `punt` are already
// CATEGORIES-ordered by contract (backend serializes punt_ordered, never
// the hash-order set)
function sameBuild(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((cat, i) => cat === b[i]);
}

/**
 * Suggested punt builds for the roster driving the draft (see page.tsx —
 * this reflects the mock-draft-in-progress roster once picks exist, not
 * just the Yahoo roster). Selecting one re-ranks the big board around that
 * punt (network round trip, since punt-aware value depends on the engine);
 * selecting the already-applied suggestion again clears it. Category keys
 * never render raw (e.g. "ft_pct") — always translated through
 * categoryKeys.ts first, and the backend's free-text `rationale` is never
 * shown verbatim (it's built from those same raw keys server-side).
 */
export default function PuntSuggestions({
  suggestions,
  applied,
  pendingPunt,
  error,
  onSelect,
  onClear,
}: {
  suggestions: DraftPuntSuggestion[];
  applied: string[];
  pendingPunt: string[] | null;
  error: string | null;
  onSelect: (punt: string[]) => void;
  onClear: () => void;
}) {
  if (suggestions.length === 0) {
    return (
      <p className={emptyStateClasses()}>
        No punt suggestions yet — claim a team in this league, or draft a few players in the
        mock draft below, to see build-based punt strategies.
      </p>
    );
  }

  return (
    <div>
      {error && (
        <p role="alert" className={`mb-3 ${noticeClasses()} ${proseClasses()}`}>
          <span className={noticeDotClasses("error")} aria-hidden="true" />
          {error}
        </p>
      )}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {suggestions.map((s) => {
          const isApplied = sameBuild(applied, s.punt);
          // pendingPunt is `[]` while CLEARING (the applied card is the one
          // in flight) and the target punt while APPLYING a new suggestion
          const isPending =
            pendingPunt !== null && (pendingPunt.length === 0 ? isApplied : sameBuild(pendingPunt, s.punt));
          const anyPending = pendingPunt !== null;
          const labels = s.punt.map((key) => LABEL_BY_CONTRACT_KEY[key] ?? key);
          return (
            <li key={s.punt.join(",")} className={`border p-3 ${isApplied ? "border-court" : "border-rule"}`}>
              <p className={subheadingClasses()}>
                Punt {labels.join(" + ")}
              </p>
              <p className={`mt-1 ${captionClasses()}`}>
                Weakest category: {LABEL_BY_CONTRACT_KEY[s.weakest] ?? s.weakest} (
                {formatZScore(s.weakest_mean)})
              </p>
              <button
                type="button"
                disabled={anyPending}
                aria-busy={isPending}
                onClick={() => (isApplied ? onClear() : onSelect(s.punt))}
                aria-pressed={isApplied}
                className={`mt-3 min-h-[2.25rem] w-full border-2 px-3 py-1.5 font-condensed text-ui font-semibold ${controlMotionClasses()} disabled:cursor-not-allowed disabled:opacity-60 ${
                  isApplied
                    ? "border-court bg-court text-ink-fill hover:bg-paper hover:text-court"
                    : "border-ink text-ink hover:bg-ink hover:text-paper"
                }`}
              >
                {isPending ? "Applying…" : isApplied ? "Applied — clear" : "Apply this punt"}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
