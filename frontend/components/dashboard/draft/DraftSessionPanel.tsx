"use client";

import { useEffect, useRef } from "react";
import type { DraftBoardPlayer, DraftRecommendation } from "@/lib/api";
import ErrorState from "@/components/dashboard/ErrorState";
import { SkeletonCard } from "@/components/dashboard/Skeletons";
import ExplanationsNotice from "@/components/dashboard/advisor/ExplanationsNotice";
import ModelReasoning from "@/components/dashboard/advisor/ModelReasoning";
import {
  modelRankByItemKey,
  reasoningByItemKey,
} from "@/components/dashboard/advisor/tokens";
import { formatSignedNumber } from "@/components/dashboard/format";
import { MAY_NOT_LAST_REASON, MOCK_DRAFT_TEAMS } from "./draftSession";
import type { DraftSession } from "./useDraftSession";

/**
 * Live pick-by-pick draft session: presentational shell around
 * `useDraftSession` (state now lives in the page so BigBoardTable can also
 * draft players and mark them taken). Recommendations come from the real
 * `postDraftRecommend` endpoint on the user's own turn; opponent picks are a
 * local weighted-ADP simulation (D7 — never a backend round trip).
 *
 * The slot select moved out to PageHeader's actions slot (dash regrid task
 * 9) -- the page already holds `session`, so it renders that control
 * directly rather than threading it back down through this component. The
 * reset button stays here, not in the header: e2e/draft.spec.ts scopes
 * `getByRole("button", { name: "Reset mock draft" })` to
 * `section:has(#session-heading)`, so moving it out of this section's
 * subtree would break that literal locator.
 */
export default function DraftSessionPanel({
  session,
  adpPlayers,
}: {
  session: DraftSession;
  adpPlayers: DraftBoardPlayer[];
}) {
  const {
    rounds,
    totalPicks,
    myPicks,
    lastOpponentRun,
    draftComplete,
    recStatus,
    recommendations,
    explanations,
    explanationsReason,
    recError,
    announcement,
    startSession,
    draftPlayer,
    retryRecommendations,
  } = session;

  // fix: after a pick, the clicked button unmounts and focus falls to
  // <body> -- move it to this heading (a real focus target via tabIndex)
  // so a keyboard/screen-reader user lands back on "what's next" instead of
  // having to re-tab from the top of the page for every one of 9 picks
  const headingRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (announcement) headingRef.current?.focus();
  }, [announcement]);

  const statBasisByKey = new Map(adpPlayers.map((p) => [p.player_key, p.stat_basis]));
  // keyed, not zipped: the model may rank the shortlist differently from the
  // engine, so pairing by index would attach the wrong prose to the wrong player
  const reasoningByKey = reasoningByItemKey(explanations);
  const modelRankByKey = modelRankByItemKey(explanations);

  if (rounds < 1) {
    return (
      <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
        Not enough draftable players yet for a mock draft ({adpPlayers.length} available, need
        at least {MOCK_DRAFT_TEAMS}).
      </p>
    );
  }

  const universalMayNotLast =
    recommendations.length > 0 &&
    recommendations.every((r) => r.reasons.includes(MAY_NOT_LAST_REASON));

  function reasonsFor(rec: DraftRecommendation): string[] {
    return universalMayNotLast ? rec.reasons.filter((r) => r !== MAY_NOT_LAST_REASON) : rec.reasons;
  }

  return (
    <div>
      {/* the live "Pick N of M / Round R" line used to render here too --
          removed (review fix, pass 2) now that the page's Pick/Round tiles
          own that number; keeping both was two live copies of the same
          state. The completion copy stays: it's the one thing the tiles
          can't say (they hide entirely once complete, see deriveDraftStats),
          and it belongs beside the control that acts on it. ml-auto on the
          button (not just justify-between) keeps Reset pinned to the right
          even when this line has nothing to render. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {draftComplete && (
          <p className="font-mono text-xs uppercase tracking-wide text-ink/70">
            Mock draft complete — {totalPicks} picks
          </p>
        )}
        <button
          type="button"
          onClick={startSession}
          className="ml-auto min-h-[2.25rem] border border-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wide text-ink transition-colors hover:bg-ink hover:text-paper"
        >
          Reset mock draft
        </button>
      </div>

      {/* always mounted so a text change is reliably announced, per WAI-ARIA
          live-region guidance -- conditionally mounting role="status" can
          miss the very first announcement in some screen readers */}
      <p role="status" className="sr-only">
        {announcement}
      </p>

      {lastOpponentRun.length > 0 && !draftComplete && (
        <div className="mt-4">
          <p className="font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
            Since your last turn ({lastOpponentRun.length} opponent{" "}
            {lastOpponentRun.length === 1 ? "pick" : "picks"})
          </p>
          <ul aria-label="Opponent picks since your last turn" className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            {lastOpponentRun.map((p) => (
              <li key={p.playerKey} className="font-mono text-xs text-ink/70">
                {p.name}
                {p.position ? ` (${p.position})` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!draftComplete && (
        <div className="mt-4">
          <p ref={headingRef} tabIndex={-1} className="font-mono text-xs uppercase tracking-[0.15em] text-ink/80">
            On the clock — top recommendations
          </p>

          {recStatus === "loading" && (
            <div aria-busy="true" className="mt-3">
              <p role="status" className="sr-only">
                Loading recommendations…
              </p>
              <SkeletonCard lines={4} />
            </div>
          )}

          {recStatus === "error" && (
            <div className="mt-3">
              <ErrorState message={recError ?? undefined} onRetry={retryRecommendations} />
            </div>
          )}

          {recStatus === "ready" && recommendations.length === 0 && (
            <p className="mt-3 border border-dashed border-rule px-4 py-6 text-center text-ink/80">
              No available players match this pick — the draftable pool may be exhausted.
            </p>
          )}

          {recStatus === "ready" && recommendations.length > 0 && (
            <>
              <div className="mt-3">
                <ExplanationsNotice explanations={explanations} reason={explanationsReason} />
              </div>
              <ul aria-label="Top recommendations" className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {recommendations.map((rec, i) => {
                  const isPrimary = i === 0;
                  const statBasis = statBasisByKey.get(rec.player_key);
                  return (
                    <li
                      key={rec.player_key}
                      className={`border p-3 ${isPrimary ? "border-2 border-court bg-court/[0.06]" : "border-rule"}`}
                    >
                      <p className="font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
                        #{i + 1}
                        {isPrimary ? " · Top pick" : ""}
                      </p>
                      <p className="mt-0.5 font-display text-base leading-tight text-ink">{rec.name}</p>
                      <p className="mt-0.5 font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
                        {rec.position ?? "—"} · value {formatSignedNumber(rec.value)}
                        {statBasis === "season_average" && (
                          <span className="ml-1.5 border border-rule px-1 py-0.5 text-[0.6rem] text-ink/80">
                            SZN AVG
                          </span>
                        )}
                      </p>
                      {reasonsFor(rec).length > 0 && (
                        <ul className="mt-2 space-y-1 text-xs text-ink/80">
                          {reasonsFor(rec).map((reason) => (
                            <li key={reason}>{reason}</li>
                          ))}
                        </ul>
                      )}
                      <ModelReasoning
                        reasoning={reasoningByKey.get(rec.player_key)}
                        modelRank={modelRankByKey.get(rec.player_key)}
                        engineRank={i + 1}
                      />
                      <button
                        type="button"
                        onClick={() =>
                          draftPlayer({ playerKey: rec.player_key, name: rec.name, position: rec.position })
                        }
                        className={`mt-3 min-h-[2.25rem] w-full px-3 py-1.5 font-mono text-xs uppercase tracking-wide transition-colors duration-200 ${
                          isPrimary
                            ? "border-2 border-court bg-court text-ink-fill hover:bg-paper hover:text-court"
                            : "border-2 border-ink text-ink hover:bg-ink hover:text-paper"
                        }`}
                      >
                        Draft
                      </button>
                    </li>
                  );
                })}
              </ul>
              {universalMayNotLast && (
                <p className="mt-2 font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
                  Depth is thin at this point in the draft — most of this list may not last to
                  your next pick.
                </p>
              )}
            </>
          )}
        </div>
      )}

      {draftComplete && (
        <p className="mt-4 max-w-prose text-ink/80">Mock draft complete. Reset to run it again.</p>
      )}

      <div className="mt-6">
        <p className="font-mono text-xs uppercase tracking-wide text-ink/70">
          Your picks ({myPicks.length})
        </p>
        {myPicks.length === 0 ? (
          <p className="mt-1 text-xs text-ink/70">None yet</p>
        ) : (
          <ol className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            {myPicks.map((p, i) => (
              <li key={p.playerKey} className="font-mono text-xs text-ink/80">
                {i + 1}. {p.name}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
