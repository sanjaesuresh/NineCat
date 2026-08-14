"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getLeagueMatchup,
  refreshLeague,
  isUnauthorized,
  ApiError,
  type LeagueMatchupResponse,
} from "@/lib/api";
import BuildProfile from "@/components/dashboard/BuildProfile";
import StaleBanner from "@/components/dashboard/StaleBanner";
import ErrorState from "@/components/dashboard/ErrorState";
import { SkeletonCard, SkeletonTable } from "@/components/dashboard/Skeletons";
import ProjectedScoreboard from "@/components/dashboard/matchup/ProjectedScoreboard";
import FocusCategories from "@/components/dashboard/matchup/FocusCategories";
import ScheduleCoverageNotice from "@/components/dashboard/matchup/ScheduleCoverageNotice";
import OpponentEmptyState from "@/components/dashboard/matchup/OpponentEmptyState";
import ExplanationsNotice from "@/components/dashboard/advisor/ExplanationsNotice";
import AddScheduleTable from "@/components/dashboard/matchup/AddScheduleTable";
import { formatWeekRange, formatSlotDay } from "@/components/dashboard/matchup/format";

type Status = "loading" | "ready" | "error";

export default function MatchupPage() {
  const params = useParams<{ leagueId: string }>();
  const router = useRouter();
  const leagueId = Number(params.leagueId);

  const [status, setStatus] = useState<Status>("loading");
  const [matchup, setMatchup] = useState<LeagueMatchupResponse | null>(null);
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
      const res = await getLeagueMatchup(leagueId);
      setMatchup(res);
      setStatus("ready");
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/");
        return;
      }
      setErrorMessage(
        err instanceof ApiError
          ? `Couldn't load this matchup (${err.status}).`
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
    <main className="mx-auto min-w-0 w-full max-w-4xl px-6 py-10 sm:px-10 sm:py-14">
      <h1 className="font-display text-3xl text-ink">Matchup</h1>

      {status === "loading" && (
        <div className="mt-8 space-y-8" aria-busy="true">
          <p role="status" className="sr-only">
            Loading matchup…
          </p>
          <SkeletonCard lines={2} />
          <SkeletonTable rows={9} cols={4} />
          <SkeletonCard lines={4} />
        </div>
      )}

      {status === "error" && (
        <div className="mt-8">
          <ErrorState message={errorMessage ?? undefined} onRetry={load} />
        </div>
      )}

      {status === "ready" && matchup && (
        <MatchupContent matchup={matchup} onRefresh={handleRefresh} onRetry={load} />
      )}
    </main>
  );
}

function MatchupContent({
  matchup,
  onRefresh,
  onRetry,
}: {
  matchup: LeagueMatchupResponse;
  onRefresh: () => Promise<void>;
  onRetry: () => void;
}) {
  const { opponent, comparison, schedule_coverage: coverage } = matchup;
  // one shared reason drives both the scoreboard and the focus-categories
  // section, so the two never disagree about why the comparison isn't shown
  const blockedReason: "no_opponent" | "no_schedule" | null =
    opponent === null ? "no_opponent" : !coverage.ok ? "no_schedule" : null;
  const canCompare = blockedReason === null && opponent !== null && comparison !== null;

  return (
    <div className="mt-8 space-y-10">
      {matchup.stale && <StaleBanner syncedAt={matchup.synced_at} onRefresh={onRefresh} />}

      <p className="font-mono text-xs uppercase tracking-wide text-ink/70">
        Week {matchup.week} ·{" "}
        {formatWeekRange(matchup.week_range.start_date, matchup.week_range.end_date)}
        {matchup.week_range.is_derived && (
          <span className="ml-2 normal-case text-ink/70">
            (dates estimated — not confirmed by Yahoo)
          </span>
        )}
        {" · "}Data as of {formatSlotDay(matchup.as_of)}
      </p>

      <section aria-labelledby="scoreboard-heading">
        <h2 id="scoreboard-heading" className="font-display text-xl text-ink">
          Projected scoreboard
        </h2>
        <div className="mt-3">
          {blockedReason === "no_opponent" && (
            <OpponentEmptyState
              reason={matchup.opponent_reason}
              mine={matchup.mine}
              coverage={coverage}
            />
          )}
          {blockedReason === "no_schedule" && <ScheduleCoverageNotice coverage={coverage} />}
          {canCompare && opponent && comparison && (
            <ProjectedScoreboard mine={matchup.mine} opponent={opponent} comparison={comparison} />
          )}
          {blockedReason === null && !canCompare && (
            <ErrorState
              message="The matchup comparison didn't come back with this response."
              onRetry={onRetry}
            />
          )}
        </div>
      </section>

      <section aria-labelledby="focus-heading">
        <h2 id="focus-heading" className="font-display text-xl text-ink">
          Focus categories
        </h2>
        <div className="mt-3">
          {canCompare && comparison ? (
            <FocusCategories focus={comparison.focus} categories={comparison.categories} />
          ) : (
            <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
              {blockedReason === "no_opponent"
                ? "Focus categories need a known opponent."
                : "Focus categories need real schedule data for this week."}
            </p>
          )}
        </div>
      </section>

      <section aria-labelledby="builds-heading">
        <h2 id="builds-heading" className="font-display text-xl text-ink">
          Category builds
        </h2>
        <div className="mt-3 grid gap-6 md:grid-cols-2">
          <div>
            <p className="mb-2 font-mono text-xs uppercase tracking-wide text-ink/70">
              {matchup.mine.name}
            </p>
            <BuildProfile profile={matchup.mine.build_profile} />
          </div>
          <div>
            <p className="mb-2 font-mono text-xs uppercase tracking-wide text-ink/70">
              {opponent ? opponent.name : "Opponent"}
            </p>
            {opponent ? (
              <BuildProfile profile={opponent.build_profile} />
            ) : (
              <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
                No opponent build available.
              </p>
            )}
          </div>
        </div>
      </section>

      <section aria-labelledby="streaming-heading">
        <h2 id="streaming-heading" className="font-display text-xl text-ink">
          Add schedule
        </h2>
        <div className="mt-3">
          {/* the optimizer runs off the same weekly schedule query as the
              scoreboard — when that's missing, an empty streaming plan would
              read as "the optimizer looked and found nothing" rather than
              "we have no schedule", the same false-confidence failure one
              section up, so this is gated on the same blockedReason */}
          {blockedReason === "no_schedule" ? (
            <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
              The add-schedule optimizer needs real game data for this week — it will fill in once
              the schedule next syncs.
            </p>
          ) : (
            <>
              <div className="mb-3">
                <ExplanationsNotice
                  explanations={matchup.explanations}
                  reason={matchup.explanations_reason}
                />
              </div>
              <AddScheduleTable
                streaming={matchup.streaming}
                asOf={matchup.as_of}
                weekRange={matchup.week_range}
                explanations={matchup.explanations}
              />
            </>
          )}
        </div>
      </section>
    </div>
  );
}
