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
import { SkeletonCard, SkeletonStatRow, SkeletonTable } from "@/components/dashboard/Skeletons";
import PageHeader from "@/components/dashboard/layout/PageHeader";
import Panel from "@/components/dashboard/layout/Panel";
import StatRow from "@/components/dashboard/layout/StatRow";
import StatTile from "@/components/dashboard/layout/StatTile";
import { deriveTeamStats } from "@/components/dashboard/stats/deriveTeamStats";
import { categoryLabelOrGap } from "@/components/dashboard/categoryKeys";

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

  // derived once data is in, never fetched separately -- every field here
  // comes from the overview/team payloads this page already loaded
  const stats = overview && team ? deriveTeamStats(overview, team) : null;

  return (
    <main className="min-w-0 w-full">
      <PageHeader
        title="My Team"
        actions={
          stale && syncedAt ? (
            <StaleBanner variant="chip" syncedAt={syncedAt} onRefresh={handleRefresh} />
          ) : undefined
        }
      />

      <div className="mt-4 space-y-4 px-6 sm:px-10">
        {status === "loading" && (
          <div aria-busy="true">
            <p role="status" className="sr-only">
              Loading roster…
            </p>
            <div className="space-y-4">
              <SkeletonStatRow tiles={4} />
              <SkeletonTable rows={6} cols={12} />
              <div className="grid gap-4 lg:grid-cols-2">
                <SkeletonCard lines={4} />
                <SkeletonCard lines={5} />
              </div>
              {/* This week: a two-row table shape (team vs. opponent x 9 categories),
                  matching MatchupStrip's own table so the section doesn't reflow when data lands */}
              <SkeletonTable rows={2} cols={10} />
            </div>
          </div>
        )}

        {status === "error" && (
          <Panel title="Team status">
            <ErrorState message={errorMessage ?? undefined} onRetry={load} />
          </Panel>
        )}

        {status === "ready" && overview && team && stats && (
          <>
            {(stats.record ||
              stats.rank ||
              stats.strongest.length > 0 ||
              stats.weakest.length > 0) && (
              <StatRow>
                {stats.record && <StatTile label="Record" value={stats.record} />}
                {stats.rank && <StatTile label="Rank" value={stats.rank} />}
                {stats.strongest.length > 0 && (
                  <StatTile
                    label="Strongest"
                    value={stats.strongest.map(categoryLabelOrGap).join(" + ")}
                  />
                )}
                {stats.weakest.length > 0 && (
                  <StatTile
                    label="Weakest"
                    value={stats.weakest.map(categoryLabelOrGap).join(" + ")}
                  />
                )}
              </StatRow>
            )}

            <Panel title="Roster" flush>
              <RosterTable roster={team.roster} />
            </Panel>

            {/* min-w-0 on each grid child: CSS grid items default to
                min-width: auto, which lets an implicit single column size to
                its content's min-content width (BuildProfile's table) rather
                than the track below the lg breakpoint, blowing out the page's
                horizontal scroll -- see globals.css's mobile-overflow note */}
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Category build" className="min-w-0">
                <BuildProfile profile={team.build_profile} />
              </Panel>
              <Panel title="Standings" className="min-w-0">
                <StandingsCard standings={overview.standings} myTeamId={overview.my_team_id} />
              </Panel>
            </div>

            {/* full-width: the matchup table has a team column plus 9 category
                columns, which reads cramped squeezed into a half-width panel
                next to Category build/Standings, so it gets its own row */}
            <Panel title="This week">
              <MatchupStrip matchup={overview.matchup} />
            </Panel>
          </>
        )}
      </div>
    </main>
  );
}
