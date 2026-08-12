import type { BuildProfile as BuildProfileData } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { classifyBuildLabel, formatStatValue, type BuildTone } from "./format";

// Encoding decision (see dataviz skill): `means` mixes incompatible units across
// the 9 categories (points averages vs. shooting percentages vs. turnovers), so
// they can't share one linear bar scale without fabricating a false comparison.
// Instead each category is a small multiple: a 3-segment ordinal meter driven
// purely by the backend's own strong/average/punt classification (never by the
// raw number), with the exact mean value printed underneath as ground truth.
// This mirrors CategoryLedger's box-score table so the build profile reads as
// the same signature motif, not a bolted-on chart.
const TONE_FILL: Record<BuildTone, string> = {
  strong: "bg-court",
  average: "bg-ink/35",
  punt: "bg-alert",
};
const TONE_SEGMENTS: Record<BuildTone, number> = {
  strong: 3,
  average: 2,
  punt: 1,
};
const TONE_TEXT: Record<BuildTone, string> = {
  strong: "Strong",
  average: "Average",
  punt: "Punt",
};

function BuildMeter({ tone }: { tone: BuildTone }) {
  const filled = TONE_SEGMENTS[tone];
  return (
    <span className="flex items-center justify-center gap-0.5" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={`h-1.5 w-3 rounded-sm ${i < filled ? TONE_FILL[tone] : "bg-ink/10"}`}
        />
      ))}
    </span>
  );
}

export default function BuildProfile({ profile }: { profile: BuildProfileData }) {
  return (
    <div>
      <div className="overflow-x-auto border border-rule">
        <table className="w-full border-collapse text-left">
          <caption className="sr-only">Category build: strong, average, or punt for each category</caption>
          <thead>
            <tr className="border-b-2 border-ink">
              {CATEGORIES.map((cat) => (
                <th
                  key={cat}
                  scope="col"
                  className="whitespace-nowrap border-r border-rule px-1 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70 last:border-r-0"
                >
                  {cat}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              {CATEGORIES.map((cat) => {
                const tone = classifyBuildLabel(profile.labels?.[cat]);
                return (
                  <td
                    key={cat}
                    className="whitespace-nowrap border-r border-rule px-1 py-3 text-center last:border-r-0"
                  >
                    <BuildMeter tone={tone} />
                    <span className="sr-only">{TONE_TEXT[tone]}</span>
                    <div className="mt-1 font-mono text-xs text-ink/80">
                      {formatStatValue(cat, profile.means?.[cat])}
                    </div>
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5" aria-hidden="true">
        {(["strong", "average", "punt"] as const).map((tone) => (
          <li key={tone} className="flex items-center gap-1.5 font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
            <span className={`h-1.5 w-1.5 rounded-full ${TONE_FILL[tone]}`} />
            {TONE_TEXT[tone]}
          </li>
        ))}
      </ul>
    </div>
  );
}
