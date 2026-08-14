import { isVerdictToken, type VerdictToken } from "./tokens";

// Same pill construction as matchup/VerdictBadge: border + dot carry the
// colour, the text stays full-contrast ink, so the state is never conveyed by
// colour alone.
const TONE: Record<VerdictToken, { label: string; border: string; dot: string }> = {
  favors_me: { label: "Favors you", border: "border-court", dot: "bg-court" },
  // not a failure -- a trade that favours the other side is a legitimate,
  // honestly-labelled result, so it gets caution amber rather than alert red
  favors_them: { label: "Favors them", border: "border-amber", dot: "bg-amber" },
  balanced: { label: "Balanced", border: "border-ink/50", dot: "bg-ink/50" },
  // the only value that means "don't do this": it collapses one of your strong
  // categories, which trade_eval.py forces regardless of net value
  rejected: { label: "Not worth it", border: "border-alert", dot: "bg-alert" },
};

/** Renders TradeVerdict.verdict. An unknown value renders as an explicit gap, never as one of the four. */
export default function TradeVerdictBadge({ verdict }: { verdict: string }) {
  if (!isVerdictToken(verdict)) {
    return (
      <span className="font-mono text-xs text-ink/80">Unrecognized verdict ({verdict})</span>
    );
  }
  const { label, border, dot } = TONE[verdict];
  return (
    <span
      className={`inline-flex w-fit items-center gap-1.5 border px-1.5 py-0.5 font-mono text-[0.65rem] uppercase tracking-wide text-ink ${border}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
      {label}
    </span>
  );
}
