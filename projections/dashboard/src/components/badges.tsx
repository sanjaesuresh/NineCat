import type { ConfidenceBand, InjuryRiskLabel } from "../lib/types";

// bg-*-900/text-*-200 pairs, chosen for comfortable contrast on the dark
// slate surface (well clear of WCAG AA's 4.5:1 body-text floor).
const INJURY_STYLES: Record<InjuryRiskLabel, string> = {
  low: "bg-emerald-900 text-emerald-200",
  moderate: "bg-amber-900 text-amber-200",
  high: "bg-rose-900 text-rose-200",
};

const INJURY_LABEL_TEXT: Record<InjuryRiskLabel, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
};

/** Small pill for availability.injury_risk_label. Text is always present (not
 * color-only), so the label reads fine without relying on hue perception. */
export function InjuryChip({ label }: { label: InjuryRiskLabel }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${INJURY_STYLES[label]}`}
    >
      {INJURY_LABEL_TEXT[label]}
    </span>
  );
}

const CONFIDENCE_STYLES: Record<ConfidenceBand, string> = {
  HIGH: "bg-emerald-900 text-emerald-200",
  MEDIUM: "bg-amber-900 text-amber-200",
  LOW: "bg-rose-900 text-rose-200",
};

/** Pill for model.confidence_band, paired next to the raw numeric score. */
export function ConfidenceChip({ band }: { band: ConfidenceBand }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${CONFIDENCE_STYLES[band]}`}
    >
      {band === "HIGH" ? "High" : band === "MEDIUM" ? "Medium" : "Low"}
    </span>
  );
}

/**
 * Consensus disagreement marker: only renders when |rank_difference| >= 15,
 * matching the brief's threshold for "worth calling out." Positive
 * rank_difference means the model ranks the player higher (better) than
 * consensus, so it gets the "up/green" treatment; negative gets "down/red."
 * The visible glyph is decorative -- the sr-only text carries the meaning
 * for screen readers.
 */
export function RankDeltaMarker({ rankDifference }: { rankDifference: number | null }) {
  if (rankDifference === null || Math.abs(rankDifference) < 15) return null;

  const modelHigher = rankDifference > 0;
  return (
    <span
      className={`ml-1 inline-flex items-center text-xs font-semibold ${
        modelHigher ? "text-emerald-400" : "text-rose-400"
      }`}
    >
      <span aria-hidden="true">{modelHigher ? "▲" : "▼"}</span>
      <span className="sr-only">
        {modelHigher
          ? `Model ranks this player ${Math.round(Math.abs(rankDifference))} spots higher than consensus`
          : `Model ranks this player ${Math.round(Math.abs(rankDifference))} spots lower than consensus`}
      </span>
    </span>
  );
}
