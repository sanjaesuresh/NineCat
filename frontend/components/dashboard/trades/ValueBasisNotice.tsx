import { captionClasses, proseClasses } from "@/components/dashboard/layout/typography";
import { noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";
// LeagueTradesResponse.value_basis. Typed as an explicit union for the same
// reason every other token map on the dashboard is: a new basis landing on the
// backend without a matching disclosure here must be a compile error, because
// the disclosure is the mitigation for a real modelling limitation, not decoration.
const VALUE_BASIS_TOKENS = ["category_impact_only"] as const;
type ValueBasisToken = (typeof VALUE_BASIS_TOKENS)[number];

const VALUE_BASIS_COPY: Record<ValueBasisToken, string> = {
  category_impact_only:
    "Verdicts weigh category impact only — not positional scarcity. Two centers for one better center can read neutral here while leaving you unable to fill a starting slot.",
};

function isValueBasisToken(token: string): token is ValueBasisToken {
  return (VALUE_BASIS_TOKENS as readonly string[]).includes(token);
}

/**
 * What the verdict does not account for. Standing and non-dismissible: the
 * trade analyzer is the easiest place in this product to be confidently wrong,
 * since it advises on a decision the user cannot undo
 * (docs/trade-analyzer-plan.md, risks).
 *
 * The acceptance caveat leads. On a lopsided league every top proposal reads
 * "favors you", and without that sentence first the list reads as four trades
 * you should go and make rather than four asks worth making.
 */
export default function ValueBasisNotice({
  valueBasis,
  evaluated,
  truncated,
  hasProposals,
}: {
  valueBasis: string;
  evaluated: number;
  truncated: boolean;
  hasProposals: boolean;
}) {
  return (
    <div className={noticeClasses()}>
      <span className={noticeDotClasses("warn")} aria-hidden="true" />
      <div className={`min-w-0 ${proseClasses()}`}>
        <p>
          Nothing here models whether the other manager would accept. Both sides have to improve a
          real weakness for a trade to appear, but these are ranked by what they do for{" "}
          <em>your</em> build — not by how likely they are to be agreed.
        </p>
        <p className="mt-2">
          {isValueBasisToken(valueBasis)
            ? VALUE_BASIS_COPY[valueBasis]
            : `Unrecognized value basis (${valueBasis}) — this disclosure needs a translation.`}
        </p>
        {hasProposals && (
          <p className={`mt-2 ${proseClasses("muted")}`}>
            Net category swing is the change in your summed category z-scores — positive means your
            nine-category totals improve overall. It is a relative measure, not a rating out of ten.
          </p>
        )}
        <p className={`mt-2 ${proseClasses("muted")}`}>
          Not modelled at all: rest-of-season schedule, playoff weeks, injury risk beyond games
          played.
        </p>
        <p className={`mt-2 ${captionClasses()}`}>
          {evaluated.toLocaleString()} combination{evaluated === 1 ? "" : "s"} examined
          {truncated && " · stopped early, so this is not the whole search space"}
        </p>
      </div>
    </div>
  );
}
