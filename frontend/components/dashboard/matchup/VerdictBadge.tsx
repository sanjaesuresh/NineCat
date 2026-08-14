// Same pill shape as InjuryBadge/DashboardNav's "Soon" badge: border + dot
// carry the color, text stays full-contrast ink — accent color never carries
// meaning on its own, so this reads correctly even for someone who can't
// distinguish the border color.
const TONE: Record<
  "winning" | "losing" | "close" | "tie",
  { label: string; border: string; dot: string }
> = {
  winning: { label: "Winning", border: "border-court", dot: "bg-court" },
  losing: { label: "Losing", border: "border-alert", dot: "bg-alert" },
  close: { label: "Close", border: "border-amber", dot: "bg-amber" },
  // "tie" is its own visual state, not a fallback of winning/losing — a dead-level
  // category (e.g. 45-45) must never quietly read as a win or a loss. Border
  // uses ink/50 rather than --rule (~1.95:1, reads as a rendering glitch next
  // to the other three visibly-bordered pills) — the label itself already
  // carries full-contrast "Tied" text, so this is purely about the pill being
  // visible as a pill, not about color conveying the state.
  tie: { label: "Tied", border: "border-ink/50", dot: "bg-ink/50" },
};

function isVerdict(v: string | null | undefined): v is keyof typeof TONE {
  return v === "winning" || v === "losing" || v === "close" || v === "tie";
}

/** Renders the backend's 4-value category verdict. Unknown/missing verdicts render as a plain dash, never silently as one of the four. */
export default function VerdictBadge({ verdict }: { verdict: string | null | undefined }) {
  if (!isVerdict(verdict)) {
    return <span className="font-mono text-xs text-ink/70">—</span>;
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
