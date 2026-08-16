import type { ModelExplanations } from "@/lib/api";
import { describeExplanationsReason } from "./tokens";
import { captionClasses } from "@/components/dashboard/layout/typography";
import { noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";

/**
 * The header for a model-explained list: either the model's own summary, named
 * and attributed, or an honest note about why there isn't one.
 *
 * Absent explanations are a first-class mode, not an error state
 * (docs/claude-advisor-plan.md A2) -- so the unavailable branch is deliberately
 * NOT the page's error styling. Nothing has failed for the user: the engine's
 * ranking below is complete and unchanged, and the note says exactly that.
 */
export default function ExplanationsNotice({
  explanations,
  reason,
}: {
  explanations: ModelExplanations | null;
  reason: string | null;
}) {
  if (explanations) {
    return (
      <div className={noticeClasses()}>
        <span className={noticeDotClasses("info")} aria-hidden="true" />
        <div className="min-w-0">
          <p className={captionClasses()}>
            Written by {explanations.model} · advisory, not arithmetic
          </p>
          <p className="mt-1 text-ink">{explanations.summary}</p>
        </div>
      </div>
    );
  }

  const note = describeExplanationsReason(reason);
  // no reason worth stating (or none given) -- show nothing rather than an
  // empty box explaining an absence the user never noticed
  if (!note) return null;

  return (
    <p role="status" className={captionClasses()}>
      {note}
    </p>
  );
}
