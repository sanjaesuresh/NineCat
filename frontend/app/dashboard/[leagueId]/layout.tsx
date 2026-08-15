"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getMe, isUnauthorized, type League } from "@/lib/api";
import DashboardShell from "@/components/dashboard/layout/DashboardShell";

/**
 * Wraps every page scoped to one league (My Team, Settings, ...) with the
 * sidebar shell. Resolves the league's display name AND the full leagues
 * array from getMe() -- the name labels the league switcher's disabled
 * placeholder option when the current league isn't in the fetched list yet,
 * the array populates the switcher's real options -- purely best-effort and non-blocking,
 * since neither getLeagueOverview nor getLeagueTeam return the league's
 * name/season. Child pages fetch their own data independently and handle
 * their own loading/error/401 states, so this never gates rendering of
 * `children`.
 */
export default function LeagueLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ leagueId: string }>();
  const router = useRouter();
  const [leagueName, setLeagueName] = useState<string | null>(null);
  const [leagues, setLeagues] = useState<League[]>([]);
  // distinguishes "still fetching" from "fetch settled with zero leagues" --
  // the latter is reachable (any non-unauthorized getMe error is swallowed
  // below) and permanent, so the sidebar's league switcher needs to know
  // when it's safe to stop showing "Loading…"
  const [leaguesLoaded, setLeaguesLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => {
        if (cancelled) return;
        setLeagues(me.leagues);
        const match = me.leagues.find((l) => String(l.id) === params.leagueId);
        // clear stale name on no match -- otherwise a route change to a
        // leagueId absent from the fetched list (e.g. back/forward to a
        // league since removed) leaves the PREVIOUS league's name showing
        setLeagueName(match ? match.name : null);
      })
      .catch((err) => {
        if (!cancelled && isUnauthorized(err)) router.replace("/");
        // any other error here is non-fatal — the shell just shows no league
        // name/switcher options yet, and the page below will surface its own
        // error from its own fetch
      })
      .finally(() => {
        if (!cancelled) setLeaguesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [params.leagueId, router]);

  return (
    <DashboardShell
      leagueId={params.leagueId}
      leagueName={leagueName}
      leagues={leagues}
      leaguesLoaded={leaguesLoaded}
    >
      {children}
    </DashboardShell>
  );
}
