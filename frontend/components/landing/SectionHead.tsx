// server component: no interactivity, so it never needs "use client" and can be
// reused inside any section (live or coming-soon) without growing the client bundle.
// mirrors the mockup's .sec-head / .monogram / .kicker / .sec-pitch / .print-tag markup.

export type SectionStatus = "live" | "soon";

export interface SectionHeadProps {
  /** single glyph shown in the monogram block, e.g. "D" for Draft Board. */
  monogram: string;
  /** ordinal shown in the kicker line, e.g. 1 -> "Tool No. 1". */
  toolNumber: number;
  /** id placed on the rendered <h2>, so the caller's <section> can aria-labelledby it. */
  headingId: string;
  heading: string;
  pitch: string;
  /** drives the print-tag's live vs. coming-soon styling. */
  status: SectionStatus;
  /** print-tag copy — kept separate from `status` since live tags vary per tool
      (e.g. "This Draft Season") while soon tags are usually just "Coming Soon". */
  statusLabel: string;
}

export default function SectionHead({
  monogram,
  toolNumber,
  headingId,
  heading,
  pitch,
  status,
  statusLabel,
}: SectionHeadProps) {
  return (
    <div className="mb-7 flex flex-col items-start gap-5 sm:flex-row sm:flex-wrap sm:justify-between">
      <div className="flex items-start gap-[18px]">
        <span
          aria-hidden="true"
          className="flex h-14 w-14 shrink-0 items-center justify-center bg-alert-fill font-display text-3xl text-cream"
        >
          {monogram}
        </span>
        <div>
          <span className="mb-1.5 block font-condensed text-sm font-bold uppercase tracking-[0.1em] text-red-ink">
            Tool No. {toolNumber}
          </span>
          <h2
            id={headingId}
            className="font-display text-[clamp(26px,3vw,38px)] leading-[1.05] text-ink"
          >
            {heading}
          </h2>
          <p className="mt-2 max-w-[52ch] text-base leading-relaxed text-ink-muted">{pitch}</p>
        </div>
      </div>
      <span
        className={`self-start whitespace-nowrap border-2 px-3.5 py-2 font-condensed text-xs font-extrabold uppercase tracking-[0.1em] ${
          status === "live"
            ? "border-ink bg-ink-fill text-cream"
            : "border-ink-muted bg-transparent text-ink-muted"
        }`}
      >
        {statusLabel}
      </span>
    </div>
  );
}
