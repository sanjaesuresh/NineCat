import type { ModelExplanations } from "@/lib/api";
import { describeExplanationsReason } from "./tokens";

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
      <div className="border-l-4 border-court bg-court/[0.05] px-4 py-3">
        <p className="font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
          Written by {explanations.model} · advisory, not arithmetic
        </p>
        <p className="mt-1 text-ink">{explanations.summary}</p>
      </div>
    );
  }

  const note = describeExplanationsReason(reason);
  // no reason worth stating (or none given) -- show nothing rather than an
  // empty box explaining an absence the user never noticed
  if (!note) return null;

  return (
    <p role="status" className="font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
      {note}
    </p>
  );
}
