import type { BuildProfile as BuildProfileData } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { classifyBuildLabel, formatZScore, type BuildTone } from "./format";
import { CONTRACT_KEY_BY_LABEL } from "./categoryKeys";
import { columnHeaderClasses, eyebrowClasses, subheadingClasses, uiTextClasses } from "@/components/dashboard/layout/typography";
import { emptyStateClasses } from "@/components/dashboard/layout/layoutTokens";

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

/**
 * `showLegend` exists for callers that render several of these together (the
 * trade card stacks four: both rosters, before and after). Repeating the same
 * four-item key under every table is noise that makes the group harder to
 * read, not easier -- one legend per group is enough.
 */
export default function BuildProfile({
  profile,
  showLegend = true,
}: {
  profile: BuildProfileData;
  showLegend?: boolean;
}) {
  const hasLabels = profile.labels && Object.keys(profile.labels).length > 0;

  if (!hasLabels) {
    return (
      <p className={emptyStateClasses()}>
        No build data yet — this fills in once your roster has season averages.
      </p>
    );
  }

  // tabIndex + named region: keyboard scroll access once the table overflows
  // (WCAG 2.1.1) -- see RosterTable for the full reasoning. aria-label rather
  // than aria-labelledby matters most here: the trade card stacks four of
  // these, so a static caption id would collide
  const caption = "Category build — mean z-score per category";
  return (
    <div>
      {/* relative: this wrapper is the live blocker — its sr-only status/legend
          spans are absolutely positioned, so without a positioning context here
          they escape to the initial containing block and stretch the page */}
      <div
        className="relative overflow-x-auto border border-rule"
        tabIndex={0}
        role="region"
        aria-label={caption}
      >
        <table className="w-full border-collapse text-left">
          <caption className={`mb-2 text-left ${subheadingClasses()}`}>
            {caption}
          </caption>
          <thead>
            <tr className="border-b-2 border-ink">
              {CATEGORIES.map((cat) => (
                <th
                  key={cat}
                  scope="col"
                  className={`whitespace-nowrap border-r border-rule px-1 py-2 text-center ${columnHeaderClasses()} last:border-r-0`}
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
                    <div className={`mt-1 ${uiTextClasses("muted")}`}>
                      {formatZScore(profile.means?.[contractKey])}
                    </div>
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
      <ul
        className={`mt-3 flex flex-wrap gap-x-4 gap-y-1.5 ${showLegend ? "" : "hidden"}`}
        aria-hidden="true"
      >
        {(["strong", "average", "punt"] as const).map((tone) => (
          <li key={tone} className={`flex items-center gap-1.5 ${eyebrowClasses()}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${TONE_FILL[tone]}`} />
            {TONE_TEXT[tone]}
          </li>
        ))}
        <li className={`flex items-center gap-1.5 ${eyebrowClasses()}`}>
          <span className="h-1.5 w-1.5 rounded-full border border-dashed border-rule" />
          No data
        </li>
      </ul>
    </div>
  );
}
