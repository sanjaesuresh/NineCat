import { isVerdictToken, VERDICT_LABEL, type VerdictToken } from "./tokens";

// Same pill construction as matchup/VerdictBadge: border + dot carry the
// colour, the text stays full-contrast ink, so the state is never conveyed by
// colour alone. Labels come from tokens.ts's VERDICT_LABEL (not repeated
// here) so this badge and deriveTradesStats' "Best verdict" tile can never
// disagree; this map only owns the per-tone styling.
const TONE: Record<VerdictToken, { border: string; dot: string }> = {
  favors_me: { border: "border-court", dot: "bg-court" },
  // not a failure -- a trade that favours the other side is a legitimate,
  // honestly-labelled result, so it gets caution amber rather than alert red
  favors_them: { border: "border-amber", dot: "bg-amber" },
  balanced: { border: "border-ink/50", dot: "bg-ink/50" },
  // the only value that means "don't do this": it collapses one of your strong
  // categories, which trade_eval.py forces regardless of net value
  rejected: { border: "border-alert", dot: "bg-alert" },
};

/** Renders TradeVerdict.verdict. An unknown value renders as an explicit gap, never as one of the four. */
export default function TradeVerdictBadge({ verdict }: { verdict: string }) {
  if (!isVerdictToken(verdict)) {
    return (
      <span className="font-mono text-xs text-ink/80">Unrecognized verdict ({verdict})</span>
    );
  }
  const { border, dot } = TONE[verdict];
  const label = VERDICT_LABEL[verdict];
  return (
    <span
      className={`inline-flex w-fit items-center gap-1.5 border px-1.5 py-0.5 font-mono text-[0.65rem] uppercase tracking-wide text-ink ${border}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
      {label}
    </span>
  );
}
