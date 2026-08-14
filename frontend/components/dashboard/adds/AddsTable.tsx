import type { AddsCandidate, ModelExplanations } from "@/lib/api";
import ModelReasoning from "@/components/dashboard/advisor/ModelReasoning";
import { modelRankByItemKey, reasoningByItemKey } from "@/components/dashboard/advisor/tokens";
import { categoryLabelOrGap } from "@/components/dashboard/categoryKeys";
import { formatGamesCount } from "@/components/dashboard/format";
import PlayerAvatar from "@/components/dashboard/PlayerAvatar";
import { formatWaiverScore } from "./format";
import { describeReason } from "./tokens";

/**
 * Ranked free-agent candidates. Follows BigBoardTable's table conventions
 * exactly (overflow wrapper + relative, min-w, border-b-2 header, font-mono
 * stats, sr-only caption, SZN AVG badge for stat_basis fallback) so this
 * reads as the same box-score motif as the draft board rather than a new
 * pattern.
 *
 * An empty `candidates` array is a real, deliberately-designed answer here
 * (see AddsCandidate/score_waiver_candidates: a candidate that doesn't
 * actually help is DROPPED, not ranked last) -- callers must not treat it
 * as an error state, and this component renders it as "nothing on the wire
 * is worth an add," not a blank table.
 *
 * Games remaining is shown as its own column, same visual weight as Score --
 * per the plan (W2), it's the thing that makes an unfamiliar name rank
 * highly, and without it visible the list reads as broken.
 */
export default function AddsTable({
  candidates,
  windowBasis,
  explanations = null,
}: {
  candidates: AddsCandidate[];
  windowBasis: "remaining" | "full_week";
  // optional: absent explanations are a first-class mode, so the table must
  // render identically without them rather than reserving empty space
  explanations?: ModelExplanations | null;
}) {
  if (candidates.length === 0) {
    return (
      <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
        No free agent on the wire actually helps this roster this week — every candidate either
        has no games left in this window or wouldn&apos;t move a category that matters. Nothing
        here is worth an add.
      </p>
    );
  }

  const hasFallback = candidates.some((c) => c.stat_basis === "season_average");
  // keyed by item_key, never zipped: the model ranks the shortlist itself and
  // is allowed to disagree with the engine's order
  const reasoningByKey = reasoningByItemKey(explanations);
  const modelRankByKey = modelRankByItemKey(explanations);

  return (
    <div>
      {hasFallback && (
        <p className="mb-3 font-mono text-[0.65rem] uppercase tracking-wide text-ink/80">
          SZN AVG marks a candidate with no live projection, valued off last season&apos;s
          averages instead.
        </p>
      )}

      {/* relative: keeps the sr-only caption clipped inside this scroll
          container instead of escaping to the initial containing block and
          stretching the page -- a real past bug on this exact motif */}
      <div className="relative overflow-x-auto border border-rule">
        <table className="w-full min-w-[760px] border-collapse text-left">
          <caption className="sr-only">
            Available free agents ranked by projected value to this roster this week
          </caption>
          <thead>
            <tr className="border-b-2 border-ink">
              <th
                scope="col"
                className="px-2 py-2 text-right font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Rank
              </th>
              <th
                scope="col"
                className="px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Player
              </th>
              <th
                scope="col"
                className="px-2 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Pos
              </th>
              <th
                scope="col"
                className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Score
              </th>
              <th
                scope="col"
                className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                {/* the count means the WHOLE week when as_of falls outside it,
                    so the header must not keep saying "left" -- the number is
                    right, the word would be the lie */}
                {windowBasis === "full_week" ? "Games this week" : "Games left"}
              </th>
              <th
                scope="col"
                className="border-l border-rule px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Helps
              </th>
              <th
                scope="col"
                className="border-l border-rule px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Why
              </th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate, i) => (
              <tr key={candidate.player_key} className="border-b border-rule last:border-b-0">
                <td className="px-2 py-2 text-right font-mono text-xs text-ink/80">{i + 1}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-3">
                    <PlayerAvatar src={candidate.headshot_url} />
                    <span className="flex items-center gap-1.5">
                      <span className="font-body text-ink">{candidate.name}</span>
                      {candidate.stat_basis === "season_average" && (
                        <span className="border border-rule px-1 py-0.5 font-mono text-[0.6rem] uppercase tracking-wide text-ink/80">
                          SZN AVG
                        </span>
                      )}
                    </span>
                  </div>
                </td>
                <td className="px-2 py-2 font-mono text-xs text-ink/80">
                  {candidate.position ?? "—"}
                </td>
                <td className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-sm text-ink">
                  {formatWaiverScore(candidate.score)}
                </td>
                <td className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-sm text-ink">
                  {formatGamesCount(candidate.games_remaining)}
                </td>
                <td className="border-l border-rule px-3 py-2 text-sm text-ink">
                  {candidate.categories_helped.length > 0
                    ? candidate.categories_helped.map(categoryLabelOrGap).join(", ")
                    : "—"}
                </td>
                <td className="border-l border-rule px-3 py-2 text-sm text-ink">
                  {candidate.reasons.length > 0
                    ? candidate.reasons.map(describeReason).join("; ")
                    : "—"}
                  <ModelReasoning
                    reasoning={reasoningByKey.get(candidate.player_key)}
                    modelRank={modelRankByKey.get(candidate.player_key)}
                    engineRank={i + 1}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
