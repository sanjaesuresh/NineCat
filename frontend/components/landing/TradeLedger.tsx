import { tradeSwing, type Cat, type SwingClassification } from "@/lib/puntDraft";
import ArtifactPanel from "./ArtifactPanel";
import { formatCounting, formatPct } from "./format";
import SectionHead from "./SectionHead";

// percentages print without a leading zero (".016"), counting stats to one decimal —
// matches the mockup's swing-grid formatter exactly, sign included
function formatDelta(cat: Cat, rawDelta: number): string {
  const sign = rawDelta < 0 ? "−" : "+";
  const magnitude = Math.abs(rawDelta);
  const formatted = cat === "fgp" || cat === "ftp" ? formatPct(magnitude) : formatCounting(magnitude);
  return `${sign}${formatted}`;
}

// arrow glyph carries the good/bad-for-you read on its own — never color alone
const ARROW: Record<SwingClassification, string> = {
  gain: "▲",
  concede: "▼",
  push: "•",
};

// sr-only word paired with each arrow (I2) — glyphs alone announce inconsistently
// or not at all across screen readers
const ARROW_LABEL: Record<SwingClassification, string> = {
  gain: "gain",
  concede: "conceded",
  push: "push",
};

const TILE_CLASS: Record<SwingClassification, string> = {
  gain: "bg-blue-txt/[0.08]",
  concede: "bg-red-ink/[0.08]",
  push: "",
};

const DELTA_TEXT_CLASS: Record<SwingClassification, string> = {
  gain: "text-blue-txt",
  concede: "text-red-ink",
  push: "text-ink-muted",
};

export default function TradeLedger() {
  // computed at render time per the brief — never hardcode gain/concede counts or arrows
  const swing = tradeSwing("Cade Cunningham", "Lauri Markkanen");

  return (
    <section
      id="trade"
      aria-labelledby="trade-heading"
      className="border-b-4 border-ink bg-paper-2 py-12 sm:py-16"
    >
      <div className="mx-auto max-w-6xl px-6 sm:px-10">
        <SectionHead
          monogram="T"
          toolNumber={4}
          headingId="trade-heading"
          heading="The Ledger"
          pitch="A category-impact breakdown for both sides before you say yes."
          status="soon"
          statusLabel="Coming Soon"
        />

        <ArtifactPanel
          captionLeft="Proposed Trade · Week 19"
          captionRight="Per-Cat Swing · Hashtag '25–26 Per-Game"
        >
          <div className="grid grid-cols-1 min-[640px]:grid-cols-2">
            <div className="p-4">
              {/* column label, not document structure — a heading here would skip
                  from the section's h2 straight to h4 (I3), so this stays a div
                  styled identically to the old h4 */}
              <div className="mb-3 font-condensed text-[12.5px] font-extrabold uppercase tracking-[0.08em] text-ink-muted">
                You Send
              </div>
              <div className="flex items-center justify-between gap-2.5 py-2.5 font-condensed">
                <span className="text-[15px] font-bold text-ink">
                  Cade Cunningham
                  <small className="block font-condensed text-[11px] font-semibold text-ink-muted">
                    PG · DET
                  </small>
                </span>
                <span className="self-center font-display text-sm text-red-ink">HTB #13</span>
              </div>
            </div>
            <div className="border-t-2 border-ink p-4 min-[640px]:border-t-0 min-[640px]:border-l-2">
              <div className="mb-3 font-condensed text-[12.5px] font-extrabold uppercase tracking-[0.08em] text-ink-muted">
                You Receive
              </div>
              <div className="flex items-center justify-between gap-2.5 py-2.5 font-condensed">
                <span className="text-[15px] font-bold text-ink">
                  Lauri Markkanen
                  <small className="block font-condensed text-[11px] font-semibold text-ink-muted">
                    SF · UTA
                  </small>
                </span>
                <span className="self-center font-display text-sm text-blue-txt">HTB #17</span>
              </div>
            </div>
          </div>

          <div className="border-t-2 border-ink px-4 pt-2 pb-3">
            <div className="pt-2 font-condensed text-[12.5px] font-extrabold uppercase tracking-[0.1em] text-ink-muted">
              Category swing if you accept — arrow means better or worse for you
            </div>
            <div className="grid grid-cols-3 gap-1.5 py-3 min-[900px]:grid-cols-9">
              {swing.categories.map((category) => (
                <div
                  key={category.cat}
                  className={`border border-rule px-1 pt-[9px] pb-[7px] text-center font-condensed ${TILE_CLASS[category.classification]}`}
                >
                  <span className="block text-[11px] font-extrabold uppercase tracking-[0.08em] text-ink-muted">
                    {category.label}
                  </span>
                  <span
                    className={`mt-[3px] block font-display text-base ${DELTA_TEXT_CLASS[category.classification]}`}
                  >
                    {formatDelta(category.cat, category.rawDelta)}{" "}
                    <span aria-hidden="true">{ARROW[category.classification]}</span>
                    <span className="sr-only"> {ARROW_LABEL[category.classification]}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="mx-4 mb-[18px] inline-block -rotate-[1.2deg] border-2 border-ink bg-paper px-[18px] py-3.5 font-condensed text-sm font-extrabold uppercase tracking-[0.05em] text-ink">
            Verdict:{" "}
            <b className="text-blue-txt">
              gain {swing.gain}, concede {swing.concede}
              {swing.push ? `, push ${swing.push}` : ""}
            </b>{" "}
            — you win the percentages and To, but hand over the Ast anchor. Accept only if Ast
            is one of your punts.
          </div>
        </ArtifactPanel>
      </div>
    </section>
  );
}
