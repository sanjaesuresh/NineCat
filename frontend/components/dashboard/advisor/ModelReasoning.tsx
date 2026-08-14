/**
 * One player's model-written reasoning, marked as model-written.
 *
 * The marker is not decoration. This text sits inches away from numbers the
 * engine computed, and the two must never read as the same kind of claim --
 * the user has to be able to tell which parts are arithmetic and which are
 * judgement (docs/claude-advisor-plan.md A6). A plausible-sounding wrong
 * explanation is worse than no explanation precisely because it launders the
 * recommendation next to it; the visible attribution is half the mitigation
 * (the other half is the backend's shortlist-integrity guard).
 *
 * Renders nothing when there is no reasoning for this player, so callers can
 * drop it into a list without branching.
 */
export default function ModelReasoning({
  reasoning,
  modelRank,
  engineRank,
}: {
  reasoning: string | undefined;
  // the model's 1-based position for this player, when known
  modelRank?: number;
  // the engine's 1-based position, so a disagreement can be shown rather than
  // silently resolved in favour of one of them
  engineRank?: number;
}) {
  if (!reasoning) return null;

  const disagrees =
    modelRank !== undefined && engineRank !== undefined && modelRank !== engineRank;

  return (
    <div className="mt-2 border-l-2 border-court/60 pl-2.5">
      <p className="font-mono text-[0.6rem] uppercase tracking-wide text-ink/60">
        Claude&apos;s read
        {disagrees ? ` · ranks this #${modelRank}` : ""}
      </p>
      <p className="mt-0.5 text-xs leading-snug text-ink/80">{reasoning}</p>
    </div>
  );
}
