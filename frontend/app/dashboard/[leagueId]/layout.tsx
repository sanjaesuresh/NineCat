"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getMe, isUnauthorized } from "@/lib/api";
import DashboardNav from "@/components/dashboard/DashboardNav";

/**
 * Wraps every page scoped to one league (My Team, Settings) with the
 * section nav. Resolves the league's display name from getMe() purely for
 * the nav heading — best-effort and non-blocking, since neither
 * getLeagueOverview nor getLeagueTeam return the league's name/season.
 * Child pages fetch their own data independently and handle their own
 * loading/error/401 states, so this never gates rendering of `children`.
 */
export default function LeagueLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ leagueId: string }>();
  const router = useRouter();
  const [leagueName, setLeagueName] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => {
        if (cancelled) return;
        const match = me.leagues.find((l) => String(l.id) === params.leagueId);
        if (match) setLeagueName(match.name);
      })
      .catch((err) => {
        if (!cancelled && isUnauthorized(err)) router.replace("/");
        // any other error here is non-fatal — the nav just shows no league name,
        // and the page below will surface its own error from its own fetch
      });
    return () => {
      cancelled = true;
    };
  }, [params.leagueId, router]);

  return (
    <>
      <DashboardNav leagueId={params.leagueId} leagueName={leagueName} />
      {children}
    </>
  );
}
