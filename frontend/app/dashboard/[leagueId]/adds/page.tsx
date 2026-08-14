"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getLeagueAdds,
  refreshLeague,
  isUnauthorized,
  ApiError,
  type LeagueAddsResponse,
} from "@/lib/api";
import StaleBanner from "@/components/dashboard/StaleBanner";
import ErrorState from "@/components/dashboard/ErrorState";
import { SkeletonCard, SkeletonTable } from "@/components/dashboard/Skeletons";
import ScheduleCoverageNotice from "@/components/dashboard/matchup/ScheduleCoverageNotice";
import { formatWeekRange, formatSlotDay, describeWindowDirection } from "@/components/dashboard/matchup/format";
import ExplanationsNotice from "@/components/dashboard/advisor/ExplanationsNotice";
import RankingBasis from "@/components/dashboard/adds/RankingBasis";
import AddsTable from "@/components/dashboard/adds/AddsTable";

type Status = "loading" | "ready" | "error";

// Sent explicitly rather than relying on the endpoint's own default, so the
// number the page discloses below is the number it actually asked for. The
// response carries no evaluated/truncated pair (unlike /trades), so a full
// page of candidates is indistinguishable from "the wire has exactly this
// many worth adding" -- saying which it is, is the honest minimum.
const ADDS_LIMIT = 25;

// window_basis === "full_week" means as_of fell outside the fantasy week
// (already over, or not started yet) -- games_remaining then counts the
// WHOLE week, not what's actually left to play, so these would not be adds
// a user could still make today. describeWindowDirection says which side.
const FULL_WEEK_COPY: Record<"before" | "after" | "unknown", string> = {
  before:
    "This week hasn't started yet, so games-remaining counts below reflect the whole week once it begins — not just what's left to play today.",
  after:
    "This week has already ended, so games-remaining counts below reflect the whole week that already happened — these wouldn't be adds you could still make.",
  unknown:
    "This week isn't live right now, so games-remaining counts below reflect the whole week rather than what's left today.",
};

export default function AddsPage() {
  const params = useParams<{ leagueId: string }>();
  const router = useRouter();
  const leagueId = Number(params.leagueId);

  const [status, setStatus] = useState<Status>("loading");
  const [adds, setAdds] = useState<LeagueAddsResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(leagueId)) {
      setErrorMessage("This league link looks invalid.");
      setStatus("error");
      return;
    }
    setStatus("loading");
    setErrorMessage(null);
    try {
      const res = await getLeagueAdds(leagueId, { limit: ADDS_LIMIT });
      setAdds(res);
      setStatus("ready");
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/");
        return;
      }
      setErrorMessage(
        err instanceof ApiError
          ? `Couldn't load available adds (${err.status}).`
          : "Couldn't reach NineCat. Check your connection and try again.",
      );
      setStatus("error");
    }
  }, [leagueId, router]);

  useEffect(() => {
    // standard fetch-on-mount: load() only sets the status useState already initializes it to
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function handleRefresh() {
    await refreshLeague(leagueId);
    await load();
  }

  return (
    <main className="mx-auto min-w-0 w-full max-w-5xl px-6 py-10 sm:px-10 sm:py-14">
      <h1 className="font-display text-3xl text-ink">Adds</h1>
      <p className="mt-2 max-w-2xl text-sm text-ink/80">
        Free agents ranked by how much they&apos;d actually help this roster this week — not a
        rest-of-season ranking.
      </p>

      {status === "loading" && (
        <div className="mt-8 space-y-8" aria-busy="true">
          <p role="status" className="sr-only">
            Loading available adds…
          </p>
          <SkeletonCard lines={2} />
          <SkeletonCard lines={2} />
          <SkeletonTable rows={8} cols={7} />
        </div>
      )}

      {status === "error" && (
        <div className="mt-8">
          <ErrorState message={errorMessage ?? undefined} onRetry={load} />
        </div>
      )}

      {status === "ready" && adds && <AddsContent adds={adds} onRefresh={handleRefresh} />}
    </main>
  );
}

function AddsContent({
  adds,
  onRefresh,
}: {
  adds: LeagueAddsResponse;
  onRefresh: () => Promise<void>;
}) {
  const windowDirection = describeWindowDirection(
    adds.as_of,
    adds.week_range.start_date,
    adds.week_range.end_date,
  );

  return (
    <div className="mt-8 space-y-10">
      {adds.stale && <StaleBanner syncedAt={adds.synced_at} onRefresh={onRefresh} />}

      <p className="font-mono text-xs uppercase tracking-wide text-ink/70">
        Week {adds.week} · {formatWeekRange(adds.week_range.start_date, adds.week_range.end_date)}
        {adds.week_range.is_derived && (
          <span className="ml-2 normal-case text-ink/70">
            (dates estimated — not confirmed by Yahoo)
          </span>
        )}
        {" · "}Data as of {formatSlotDay(adds.as_of)}
      </p>

      {/* schedule_coverage.ok false means this roster's (and/or the
          opponent's) games for the week couldn't be counted. It gates BOTH
          sections, not just the table: close_categories are derived from the
          same weekly projections, so rendering confident "targeting REB, AST"
          chips above a notice saying we have no schedule data is exactly the
          ungated-door bug the matchup page's C1 fix closed. */}
      {!adds.schedule_coverage.ok ? (
        <ScheduleCoverageNotice
          coverage={adds.schedule_coverage}
          withheld="a ranked list of adds"
        />
      ) : (
        <>
          <section aria-labelledby="basis-heading">
            <h2 id="basis-heading" className="font-display text-xl text-ink">
              Ranking basis
            </h2>
            <div className="mt-3">
              <RankingBasis
                closeCategories={adds.close_categories}
                opponentReason={adds.opponent_reason}
              />
            </div>
          </section>

          <section aria-labelledby="candidates-heading">
            <h2 id="candidates-heading" className="font-display text-xl text-ink">
              Ranked candidates
            </h2>
            {adds.candidates.length >= ADDS_LIMIT && (
              <p className="mt-1 text-sm text-ink/80">
                Showing the top {ADDS_LIMIT} — more free agents may clear the bar.
              </p>
            )}

            {/* the full-week caveat sits directly above the table it corrects,
                beside the games column, rather than two sections up */}
            {adds.window_basis === "full_week" && (
              <p
                role="status"
                className="mt-3 border-l-4 border-amber bg-ink/[0.03] px-4 py-3 text-sm text-ink"
              >
                {FULL_WEEK_COPY[windowDirection]}
              </p>
            )}

            <div className="mt-3">
              <ExplanationsNotice
                explanations={adds.explanations}
                reason={adds.explanations_reason}
              />
            </div>

            <div className="mt-3">
              <AddsTable
                candidates={adds.candidates}
                windowBasis={adds.window_basis}
                explanations={adds.explanations}
              />
            </div>
          </section>
        </>
      )}
    </div>
  );
}
