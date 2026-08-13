import ArtifactPanel from "./ArtifactPanel";
import DraftBoardTable from "./DraftBoardTable";
import SectionHead from "./SectionHead";

// server component: the <section>/SectionHead/ArtifactPanel shell needs no
// interactivity, so it stays server-rendered and only the punt-store-driven
// table below (DraftBoardTable) ships as client JS. Previously this whole file
// carried "use client" just because the table needed usePunts(), which pulled
// SectionHead into the client bundle here and nowhere else (design review I4) —
// splitting keeps SectionHead a server component in all four sections.
export default function DraftBoard() {
  return (
    <section id="draft" aria-labelledby="draft-heading" className="border-b-4 border-ink bg-paper py-12 sm:py-16">
      <div className="mx-auto max-w-6xl px-6 sm:px-10">
        <SectionHead
          monogram="D"
          toolNumber={1}
          headingId="draft-heading"
          heading="The Draft Board"
          pitch="Real-time 9-cat rankings — seeded from Hashtag Basketball's projections — with pick recommendations tuned to your punt build while you're on the clock."
          status="live"
          statusLabel="This Draft Season"
        />

        <ArtifactPanel
          captionLeft="On the Clock · Round 1, Pick 4"
          captionRight="Rankings: Hashtag Basketball · 9-Cat Per-Game"
        >
          <DraftBoardTable />
        </ArtifactPanel>
      </div>
    </section>
  );
}
