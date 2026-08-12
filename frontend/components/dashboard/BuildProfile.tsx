import type { BuildProfile as BuildProfileData } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { classifyBuildLabel, formatZScore, type BuildTone } from "./format";
import { CONTRACT_KEY_BY_LABEL } from "./categoryKeys";

// Encoding decision (see dataviz skill): `means` mixes incompatible units across
// the 9 categories (points averages vs. shooting percentages vs. turnovers), so
// they can't share one linear bar scale without fabricating a false comparison.
// Instead each category is a small multiple: a 3-segment ordinal meter driven
// purely by the backend's own strong/average/punt classification (never by the
// raw number), with the exact mean z-score printed underneath as ground truth.
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

// tone is null when the backend sends a missing/unrecognized label — that must
// read as "we don't know", never silently collapse into "Average"
function BuildMeter({ tone }: { tone: BuildTone | null }) {
  if (tone === null) {
    return (
      <span className="flex items-center justify-center gap-0.5" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-1.5 w-3 rounded-sm border border-dashed border-rule" />
        ))}
      </span>
    );
  }
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
  const hasLabels = profile.labels && Object.keys(profile.labels).length > 0;

  if (!hasLabels) {
    return (
      <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
        No build data yet — this fills in once your roster has season averages.
      </p>
    );
  }

  return (
    <div>
      {/* relative: this wrapper is the live blocker — its sr-only status/legend
          spans are absolutely positioned, so without a positioning context here
          they escape to the initial containing block and stretch the page */}
      <div className="relative overflow-x-auto border border-rule">
        <table className="w-full border-collapse text-left">
          <caption className="mb-2 text-left font-mono text-xs uppercase tracking-[0.15em] text-ink/70">
            Category build — mean z-score per category
          </caption>
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
                const contractKey = CONTRACT_KEY_BY_LABEL[cat];
                const tone = classifyBuildLabel(profile.labels?.[contractKey]);
                return (
                  <td
                    key={cat}
                    className="whitespace-nowrap border-r border-rule px-1 py-3 text-center last:border-r-0"
                  >
                    <BuildMeter tone={tone} />
                    <span className="sr-only">{tone === null ? "No data" : TONE_TEXT[tone]}</span>
                    <div className="mt-1 font-mono text-xs text-ink/80">
                      {formatZScore(profile.means?.[contractKey])}
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
        <li className="flex items-center gap-1.5 font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
          <span className="h-1.5 w-1.5 rounded-full border border-dashed border-rule" />
          No data
        </li>
      </ul>
    </div>
  );
}
