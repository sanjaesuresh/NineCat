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
import {
  SkeletonCard,
  SkeletonLine,
  SkeletonTable,
} from "@/components/dashboard/Skeletons";
import ProjectedScoreboard from "@/components/dashboard/matchup/ProjectedScoreboard";
import FocusCategories from "@/components/dashboard/matchup/FocusCategories";
import ScheduleCoverageNotice from "@/components/dashboard/matchup/ScheduleCoverageNotice";
import OpponentEmptyState from "@/components/dashboard/matchup/OpponentEmptyState";
import ExplanationsNotice from "@/components/dashboard/advisor/ExplanationsNotice";
import AddScheduleTable from "@/components/dashboard/matchup/AddScheduleTable";
import WeekDateLine from "@/components/dashboard/WeekDateLine";
import PageHeader from "@/components/dashboard/layout/PageHeader";
import Panel from "@/components/dashboard/layout/Panel";
import StatRow from "@/components/dashboard/layout/StatRow";
import StatTile from "@/components/dashboard/layout/StatTile";
import { deriveMatchupStats } from "@/components/dashboard/stats/deriveMatchupStats";

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

  // derived once data is in, never fetched separately -- every tile here
  // comes from the matchup payload this page already loaded
  const stats = matchup ? deriveMatchupStats(matchup) : null;

  return (
    <main className="min-w-0 w-full">
      <PageHeader title="Matchup" />

      <div className="mt-4 space-y-4 px-6 sm:px-10">
        {status === "loading" && (
          <div aria-busy="true">
            <p role="status" className="sr-only">
              Loading matchup…
            </p>
            {/* mirrors the ready-state order below (week/date line,
                scoreboard, focus + builds, add schedule) so nothing reflows
                once data lands. No StatRow skeleton: no tile is guaranteed
                here -- deriveMatchupStats returns all-null on the
                no-opponent path, and MatchupContent hides the whole StatRow
                in that case, which is exactly what the seeded dev league
                produces. Skeletoning a tile count the loading state can't
                guarantee would itself cause the row to vanish once data
                lands, the very reflow this skeleton exists to prevent (the
                Trades rule: size to the guaranteed tile, never more). */}
            <div className="space-y-4">
              <SkeletonLine className="h-3 w-64" />
              <SkeletonCard lines={4} />
              <div className="grid gap-4 lg:grid-cols-2">
                <SkeletonCard lines={3} />
                <SkeletonCard lines={3} />
              </div>
              <SkeletonTable rows={6} cols={5} />
            </div>
          </div>
        )}

        {status === "error" && (
          <Panel title="Matchup status">
            <ErrorState message={errorMessage ?? undefined} onRetry={load} />
          </Panel>
        )}

        {status === "ready" && matchup && stats && (
          <MatchupContent
            matchup={matchup}
            stats={stats}
            onRefresh={handleRefresh}
            onRetry={load}
          />
        )}
      </div>
    </main>
  );
}

function MatchupContent({
  matchup,
  stats,
  onRefresh,
  onRetry,
}: {
  matchup: LeagueMatchupResponse;
  stats: ReturnType<typeof deriveMatchupStats>;
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
    <>
      {matchup.stale && <StaleBanner syncedAt={matchup.synced_at} onRefresh={onRefresh} />}

      {(stats.opponent || stats.projected || stats.categoriesLed !== null) && (
        <StatRow>
          {stats.opponent && <StatTile label="Opponent" value={stats.opponent} />}
          {stats.projected && <StatTile label="Projected" value={stats.projected} />}
          {stats.categoriesLed !== null && (
            // "Categories winning" (verdict vocabulary), not "led" -- this counts
            // only the "winning" verdict, while the "Projected" tile above and the
            // scoreboard's big number count any positive margin including "close"
            // ones. Same category can be led without being won, so the two tiles
            // must read as visibly different quantities. Sub-line names the
            // exclusion instead of "of 9", which framed this as a share of the
            // full category set rather than a stricter count within it.
            <StatTile
              label="Categories winning"
              value={stats.categoriesLed}
              sub="excludes close leads"
            />
          )}
        </StatRow>
      )}

      <WeekDateLine week={matchup.week} weekRange={matchup.week_range} asOf={matchup.as_of} />

      <Panel title="Projected scoreboard" headingId="scoreboard-heading">
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
      </Panel>

      {/* focus categories has no wide table (a responsive card grid), so it
          pairs safely with category builds below at half width; category
          builds stacks mine/opponent vertically here (rather than the
          side-by-side layout it uses at full width elsewhere) so each single
          build table keeps the full half-column width instead of squeezing
          two tables into a quarter column each -- each build table has 9
          narrow category columns, and a quarter-width column left too little
          room per column for the meter plus its z-score text without
          wrapping */}
      {/* min-w-0 on each grid child: CSS grid items default to min-width:
          auto, which lets an implicit single column size to its content's
          min-content width (BuildProfile's table) rather than the track
          below the lg breakpoint, blowing out the page's horizontal scroll
          -- see globals.css's mobile-overflow note */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Focus categories" headingId="focus-heading" className="min-w-0">
          {canCompare && comparison ? (
            <FocusCategories focus={comparison.focus} categories={comparison.categories} />
          ) : (
            <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
              {blockedReason === "no_opponent"
                ? "Focus categories need a known opponent."
                : "Focus categories need real schedule data for this week."}
            </p>
          )}
        </Panel>

        <Panel title="Category builds" headingId="builds-heading" className="min-w-0">
          <div className="space-y-4">
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
        </Panel>
      </div>

      <Panel title="Add schedule" headingId="streaming-heading">
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
      </Panel>
    </>
  );
}
