import ArtifactPanel from "./ArtifactPanel";
import SectionHead from "./SectionHead";

interface Txn {
  readonly tag: "Add" | "Drop";
  readonly name: string;
  readonly meta: string;
}

// six waiver entries, transcribed verbatim from the mockup's .transactions block
const TXNS: readonly Txn[] = [
  {
    tag: "Add",
    name: "Isaiah Collier",
    meta: "PG · UTA — 7.2 Ast per game; the assist fix if you're chasing that column.",
  },
  {
    tag: "Drop",
    name: "Russell Westbrook",
    meta: "PG · SAC — 6.7 Ast, but it arrives with .694 Ft% and 3.3 To. Two cat taxes for one cat.",
  },
  {
    tag: "Add",
    name: "Julian Champagnie",
    meta: "SF · SA — 2.4 3pm at .844 Ft% with under one turnover; percentage-safe shooting.",
  },
  {
    tag: "Add",
    name: "Davion Mitchell",
    meta: "PG · MIA — 6.5 Ast against 1.5 To; assist volume that doesn't leak.",
  },
  {
    tag: "Drop",
    name: "Jusuf Nurkic",
    meta: "C · UTA — the Reb comes with .549 Ft%; if you're protecting Ft%, he's the leak.",
  },
  {
    tag: "Add",
    name: "Toumani Camara",
    meta: "SF · POR — 2.7 3pm and 1.1 Stl across a full 82-game slate.",
  },
];

export default function WaiverColumn() {
  return (
    <section
      id="waiver"
      aria-labelledby="waiver-heading"
      className="border-b-4 border-ink bg-paper py-12 sm:py-16"
    >
      <div className="mx-auto max-w-6xl px-6 sm:px-10">
        <SectionHead
          monogram="W"
          toolNumber={3}
          headingId="waiver-heading"
          heading="The Transactions Column"
          pitch="Surfaces the free agents actually moving the categories you're losing this week."
          status="soon"
          statusLabel="Coming Soon"
        />

        <ArtifactPanel captionLeft="Waiver Wire · Tuesday Run" captionRight="Ranked by Category Need">
          {/* CSS multi-column layout, matching the mockup's .transactions column-count:2
              (collapsing to one column below 760px) — a simple list would also work, but
              this reproduces the newspaper-column read the mockup calls for */}
          <ul className="list-none columns-1 gap-x-8 px-4 pt-1.5 pb-1 min-[760px]:columns-2">
            {TXNS.map((txn) => (
              <li
                key={txn.name}
                className="break-inside-avoid border-b border-rule py-[13px] font-condensed"
              >
                <span
                  className={`mr-2 font-extrabold text-[11px] tracking-[0.08em] uppercase ${
                    txn.tag === "Add" ? "text-blue-txt" : "text-red-ink"
                  }`}
                >
                  {txn.tag}
                </span>
                <span className="text-[15px] font-bold text-ink">{txn.name}</span>
                <span className="mt-[3px] block text-[12.5px] leading-[1.4] text-ink-muted">
                  {txn.meta}
                </span>
              </li>
            ))}
          </ul>
        </ArtifactPanel>
      </div>
    </section>
  );
}
