"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getLeagueOverview,
  getLeagueTeam,
  refreshLeague,
  isUnauthorized,
  ApiError,
  type LeagueOverviewResponse,
  type LeagueTeamResponse,
} from "@/lib/api";
import RosterTable from "@/components/dashboard/RosterTable";
import BuildProfile from "@/components/dashboard/BuildProfile";
import StandingsCard from "@/components/dashboard/StandingsCard";
import MatchupStrip from "@/components/dashboard/MatchupStrip";
import StaleBanner from "@/components/dashboard/StaleBanner";
import ErrorState from "@/components/dashboard/ErrorState";
import { SkeletonCard, SkeletonTable } from "@/components/dashboard/Skeletons";

type Status = "loading" | "ready" | "error";

export default function MyTeamPage() {
  const params = useParams<{ leagueId: string }>();
  const router = useRouter();
  const leagueId = Number(params.leagueId);

  const [status, setStatus] = useState<Status>("loading");
  const [overview, setOverview] = useState<LeagueOverviewResponse | null>(null);
  const [team, setTeam] = useState<LeagueTeamResponse | null>(null);
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
      // both panels belong to the same page and depend on the same league
      // sync, so one combined loading/error state keeps this simple rather
      // than juggling four independent states for two calls that fail together
      const [overviewRes, teamRes] = await Promise.all([
        getLeagueOverview(leagueId),
        getLeagueTeam(leagueId),
      ]);
      setOverview(overviewRes);
      setTeam(teamRes);
      setStatus("ready");
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/");
        return;
      }
      setErrorMessage(
        err instanceof ApiError
          ? `Couldn't load this league (${err.status}).`
          : "Couldn't reach NineCat. Check your connection and try again.",
      );
      setStatus("error");
    }
  }, [leagueId, router]);

  useEffect(() => {
    // standard fetch-on-mount: load() only sets the status that useState already initializes it to
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function handleRefresh() {
    await refreshLeague(leagueId);
    await load();
  }

  const stale = Boolean(overview?.stale || team?.stale);
  const syncedAt = team?.synced_at ?? overview?.synced_at ?? null;

  return (
    <main className="mx-auto min-w-0 w-full max-w-4xl px-6 py-10 sm:px-10 sm:py-14">
      <h1 className="font-display text-3xl font-semibold text-ink">My Team</h1>

      {status === "loading" && (
        <div className="mt-8 space-y-8" aria-busy="true">
          <p role="status" className="sr-only">
            Loading roster…
          </p>
          <SkeletonTable rows={6} cols={12} />
          <SkeletonCard lines={2} />
          <SkeletonCard lines={4} />
        </div>
      )}

      {status === "error" && (
        <div className="mt-8">
          <ErrorState message={errorMessage ?? undefined} onRetry={load} />
        </div>
      )}

      {status === "ready" && overview && team && (
        <div className="mt-8 space-y-10">
          {stale && syncedAt && <StaleBanner syncedAt={syncedAt} onRefresh={handleRefresh} />}

          <section aria-labelledby="roster-heading">
            <h2 id="roster-heading" className="font-display text-xl font-semibold text-ink">
              Roster
            </h2>
            <div className="mt-3">
              <RosterTable roster={team.roster} />
            </div>
          </section>

          <section aria-labelledby="build-heading">
            <h2 id="build-heading" className="font-display text-xl font-semibold text-ink">
              Category build
            </h2>
            <div className="mt-3">
              <BuildProfile profile={team.build_profile} />
            </div>
          </section>

          <section aria-labelledby="standings-heading">
            <h2 id="standings-heading" className="font-display text-xl font-semibold text-ink">
              Standings
            </h2>
            <div className="mt-3">
              <StandingsCard standings={overview.standings} myTeamId={overview.my_team_id} />
            </div>
          </section>

          <section aria-labelledby="matchup-heading">
            <h2 id="matchup-heading" className="font-display text-xl font-semibold text-ink">
              This week
            </h2>
            <div className="mt-3">
              <MatchupStrip matchup={overview.matchup} />
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
