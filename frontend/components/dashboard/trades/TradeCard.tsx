import type { TradePlayerInfo, TradeSideOutcome, TradeVerdict } from "@/lib/api";
import BuildProfile from "@/components/dashboard/BuildProfile";
import { categoryLabelOrGap } from "@/components/dashboard/categoryKeys";
import { formatSignedNumber } from "@/components/dashboard/format";
import PlayerAvatar from "@/components/dashboard/PlayerAvatar";
import TradeVerdictBadge from "./TradeVerdictBadge";
import { describeReason } from "./tokens";

function categoryList(keys: string[]): string {
  return keys.map(categoryLabelOrGap).join(", ");
}

function PlayerChip({ info, playerKey }: { info: TradePlayerInfo | undefined; playerKey: string }) {
  // an unresolved key means the response's player dictionary and its verdicts
  // disagreed -- show the key rather than an empty row, so the gap is obvious
  if (!info) {
    return <li className="font-mono text-xs text-ink/80">Unresolved player ({playerKey})</li>;
  }
  return (
    <li className="flex items-center gap-3">
      <PlayerAvatar src={info.headshot_url} />
      <span className="min-w-0">
        <span className="block truncate font-body text-ink">{info.name}</span>
        <span className="font-mono text-xs text-ink/80">{info.position ?? "—"}</span>
      </span>
    </li>
  );
}

function ProfilePair({
  heading,
  outcome,
  headingId,
  showLegend,
}: {
  heading: string;
  outcome: TradeSideOutcome;
  headingId: string;
  showLegend: boolean;
}) {
  return (
    <section aria-labelledby={headingId}>
      <h4 id={headingId} className="font-mono text-xs uppercase tracking-wide text-ink">
        {heading}
      </h4>
      <div className="mt-2 space-y-4">
        <div>
          <p className="mb-1 font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">Before</p>
          <BuildProfile profile={outcome.before} showLegend={false} />
        </div>
        <div>
          <p className="mb-1 font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">After</p>
          <BuildProfile profile={outcome.after} showLegend={showLegend} />
        </div>
      </div>
    </section>
  );
}

/**
 * One proposed trade. The summary line above the disclosure carries what you
 * gain and what you give up, so opening the four before/after profiles is
 * optional rather than necessary -- four full nine-column profiles is a wall
 * of table, and the decision is legible without it.
 *
 * The other side's movement is shown too. A tool that only lists my upside
 * reads as a sales pitch, and the generator's own keep rule requires both
 * sides to improve a real deficit, so hiding their half would misrepresent
 * why the trade was proposed at all.
 *
 * A "rejected" verdict gets different chrome, not just a different pill. It
 * is the one value that means "don't do this" -- trade_eval.py forces it when
 * the swap collapses a category you are currently strong in, whatever the net
 * value says -- and identical card styling plus a position in a ranked list
 * reads as an endorsement.
 */
export default function TradeCard({
  verdict,
  rank,
  players,
}: {
  verdict: TradeVerdict;
  rank: number;
  players: Record<string, TradePlayerInfo>;
}) {
  const detailsId = `trade-${rank}-profiles`;
  const rejected = verdict.verdict === "rejected";
  // the collapse reason is the whole point of a rejection, so it is hoisted
  // above the player names rather than sitting mid-card under them
  const collapseReasons = verdict.reasons.filter(
    (token) => token.startsWith("collapsed:") || token === "rejected",
  );
  const otherReasons = verdict.reasons.filter((token) => !collapseReasons.includes(token));

  return (
    <article className={`border p-4 sm:p-5 ${rejected ? "border-alert" : "border-rule"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h3 className="font-display text-lg text-ink">
          {rejected ? `Not recommended (${rank})` : `Proposal ${rank}`}
        </h3>
        <div className="flex flex-wrap items-center gap-3">
          <TradeVerdictBadge verdict={verdict.verdict} />
          <span className="font-mono text-xs text-ink/80">
            Net category swing {formatSignedNumber(verdict.net_value)}
          </span>
        </div>
      </div>

      {rejected && collapseReasons.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-ink">
          {collapseReasons.map((token) => (
            <li key={token}>{describeReason(token)}</li>
          ))}
        </ul>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          {/* full-ink labels with a divider: give-vs-get is the most
              consequential distinction on the card and must not be the
              faintest thing on it */}
          <h4 className="font-mono text-xs uppercase tracking-wide text-ink">You give</h4>
          <ul className="mt-2 space-y-2">
            {verdict.give.map((key) => (
              <PlayerChip key={key} playerKey={key} info={players[key]} />
            ))}
          </ul>
        </div>
        <div className="border-t border-rule pt-4 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0">
          <h4 className="font-mono text-xs uppercase tracking-wide text-ink">You get</h4>
          <ul className="mt-2 space-y-2">
            {verdict.get.map((key) => (
              <PlayerChip key={key} playerKey={key} info={players[key]} />
            ))}
          </ul>
        </div>
      </div>

      <ul className="mt-4 space-y-1 text-sm text-ink">
        {(rejected ? otherReasons : verdict.reasons).map((token) => (
          <li key={token}>{describeReason(token)}</li>
        ))}
      </ul>

      <p className="mt-3 text-sm text-ink/80">
        For them:{" "}
        {verdict.theirs.gained.length > 0
          ? `gains ${categoryList(verdict.theirs.gained)}`
          : "no category materially improves"}
        {verdict.theirs.lost.length > 0 && `, gives up ground in ${categoryList(verdict.theirs.lost)}`}
        {verdict.theirs.collapsed.length > 0 &&
          `, and collapses ${categoryList(verdict.theirs.collapsed)}`}
        .
      </p>

      <details className="mt-4 border-t border-rule pt-3">
        {/* py-1.5 pads the ~16px mono text to a 24px target (WCAG 2.2 2.5.8),
            same as Sidebar's links */}
        <summary className="inline-flex cursor-pointer items-center py-1.5 font-mono text-xs uppercase tracking-wide text-ink underline decoration-rule underline-offset-4 hover:decoration-ink">
          Before and after, both rosters
        </summary>
        <div id={detailsId} className="mt-4 space-y-6">
          <ProfilePair
            heading="Your roster"
            headingId={`${detailsId}-mine`}
            outcome={verdict.mine}
            showLegend={false}
          />
          <ProfilePair
            heading="Their roster"
            headingId={`${detailsId}-theirs`}
            outcome={verdict.theirs}
            showLegend
          />
        </div>
      </details>
    </article>
  );
}
