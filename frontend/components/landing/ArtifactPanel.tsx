import type { ReactNode } from "react";

// server component: the "print artifact" shell (heavy top rule, hairline-bordered
// caption strip, panel backdrop) shared by every table/list section — draft board,
// matchup box, waiver column, trade ledger. Extracted so the hairline token can't
// drift between sections the way it already had (design review finding I5/E1):
// every hairline in here is --rule, never the warmer/darker border-ink-muted/25
// a couple of sections had picked up independently.
export interface ArtifactPanelProps {
  /** left-aligned caption strip text, e.g. "On the Clock · Round 1, Pick 4". */
  captionLeft: string;
  /** right-aligned caption strip text, e.g. "Rankings: Hashtag Basketball · 9-Cat Per-Game". */
  captionRight: string;
  children: ReactNode;
}

export default function ArtifactPanel({
  captionLeft,
  captionRight,
  children,
}: ArtifactPanelProps) {
  return (
    <div className="border-t-4 border-ink border-b border-rule bg-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-4 py-2.5 font-condensed text-[11.5px] font-bold uppercase tracking-[0.08em] text-ink-muted">
        <span>{captionLeft}</span>
        <span>{captionRight}</span>
      </div>
      {children}
    </div>
  );
}
