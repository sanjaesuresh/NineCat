import { CATS, type Cat } from "@/lib/puntDraft";
import ArtifactPanel from "./ArtifactPanel";
import PickupCard from "./PickupCard";
import SectionHead from "./SectionHead";

// static week-19 result per category, transcribed verbatim from the mockup's box-table
// (kept as data rather than re-deriving, since this table isn't computed from POOL/tradeSwing)
const RESULTS: Record<Cat, "W" | "L"> = {
  pts: "W",
  reb: "W",
  ast: "L",
  stl: "W",
  blk: "W",
  tpm: "L",
  fgp: "W",
  ftp: "L",
  to: "W",
};

const headerCellClass =
  "bg-ink-fill px-2.5 py-2.5 text-center font-condensed text-[11px] font-extrabold uppercase tracking-[0.06em] text-cream";

function resultCellClass(result: "W" | "L"): string {
  // W/L text is the only signal that matters for a11y — color reinforces it, never replaces it
  return `px-2.5 py-2.5 text-center text-sm font-bold ${result === "W" ? "text-blue-txt" : "text-red-ink"}`;
}

export default function MatchupSection() {
  return (
    <section
      id="matchup"
      aria-labelledby="matchup-heading"
      className="border-b-4 border-ink bg-paper-2 py-12 sm:py-16"
    >
      <div className="mx-auto max-w-6xl px-6 sm:px-10">
        <SectionHead
          monogram="M"
          toolNumber={2}
          headingId="matchup-heading"
          heading="This Week's Box Score"
          pitch="Live category-by-category tracking of your weekly matchup as games finish."
          status="soon"
          statusLabel="Coming Soon"
        />

        <ArtifactPanel captionLeft="Week 19 · H2H 9-Cat" captionRight="Friday, 2 Days Remaining">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] border-collapse font-condensed">
              <caption className="sr-only">
                Week 19 box score, category by category, your squad versus this week&apos;s
                opponent.
              </caption>
              <thead>
                <tr>
                  <th scope="col" className="w-px bg-ink-fill px-2.5 py-2.5 text-left whitespace-nowrap">
                    <span className="sr-only">Team</span>
                  </th>
                  {CATS.map((cat) => (
                    <th key={cat.key} scope="col" className={headerCellClass}>
                      {cat.label}
                    </th>
                  ))}
                  <th scope="col" className="bg-maroon px-2.5 py-2.5 text-center font-condensed text-[11px] font-extrabold uppercase tracking-[0.06em] text-cream">
                    Cat
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-rule">
                  <th
                    scope="row"
                    className="w-px whitespace-nowrap bg-paper-2 px-2.5 py-2.5 text-left text-[14.5px] font-bold text-ink"
                  >
                    Your Squad
                  </th>
                  {CATS.map((cat) => (
                    <td key={cat.key} className={resultCellClass(RESULTS[cat.key])}>
                      {RESULTS[cat.key]}
                    </td>
                  ))}
                  <td className="bg-alert-fill/[0.28] px-2.5 py-2.5 text-center font-display text-base text-ink">
                    6–3
                  </td>
                </tr>
                <tr>
                  <th
                    scope="row"
                    className="w-px whitespace-nowrap bg-paper-2 px-2.5 py-2.5 text-left text-[14.5px] font-bold text-ink"
                  >
                    This Week&apos;s Opponent
                  </th>
                  {CATS.map((cat) => {
                    const oppResult = RESULTS[cat.key] === "W" ? "L" : "W";
                    return (
                      <td key={cat.key} className={resultCellClass(oppResult)}>
                        {oppResult}
                      </td>
                    );
                  })}
                  <td className="bg-alert-fill/[0.28] px-2.5 py-2.5 text-center font-display text-base text-ink">
                    3–6
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <p className="border-t-2 border-ink px-4 py-3 font-condensed text-sm font-bold uppercase tracking-[0.03em] text-ink">
            Currently <b className="text-blue-txt">winning, 6 categories to 3</b> — Ft% and
            3pm still in reach with two days of games left.
          </p>

          <div className="border-t-2 border-ink px-4 pt-3.5 pb-[18px]">
            <div className="mb-3 font-condensed text-[12.5px] font-extrabold uppercase tracking-[0.1em] text-ink-muted">
              Suggested pickups for the columns you&apos;re losing — all outside Hashtag&apos;s
              top 150, free agents in a 12-team league
            </div>
            <div className="grid grid-cols-1 gap-3.5 min-[860px]:grid-cols-3">
              <PickupCard
                personId="204456"
                name="T.J. McConnell"
                initials="TM"
                meta="PG · IND — 5.1 Ast · .862 Ft% · 1.1 To"
                fixes={["+ Ast", "+ Ft%"]}
              />
              <PickupCard
                personId="1630241"
                name="Sam Merrill"
                initials="SM"
                meta="SG · CLE — 3.0 3pm · .855 Ft% · 0.8 To"
                fixes={["+ 3pm", "+ Ft%"]}
              />
              <PickupCard
                personId="1630541"
                name="Moses Moody"
                initials="MM"
                meta="SG · GS — 2.5 3pm · 1.0 Stl"
                fixes={["+ 3pm"]}
              />
            </div>
          </div>
        </ArtifactPanel>
      </div>
    </section>
  );
}
