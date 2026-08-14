"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import LogoutButton from "./LogoutButton";

// tools not built yet, in the same season order as the landing page's roadmap
const COMING_SOON = ["Adds", "Trades"];

/** Dashboard chrome for a single league: section nav, coming-soon tools, settings, logout. */
export default function DashboardNav({
  leagueId,
  leagueName,
}: {
  leagueId: string;
  leagueName: string | null;
}) {
  const pathname = usePathname();
  const teamHref = `/dashboard/${leagueId}`;
  const draftHref = `/dashboard/${leagueId}/draft`;
  const matchupHref = `/dashboard/${leagueId}/matchup`;
  const settingsHref = `/dashboard/${leagueId}/settings`;
  const onTeam = pathname === teamHref;
  const onDraft = pathname === draftHref;
  const onMatchup = pathname === matchupHref;
  const onSettings = pathname === settingsHref;

  // inline-flex + py-1.5 pads the link's hit area to a ~24px target (WCAG 2.2
  // 2.5.8) even though the 12px mono text alone only measures ~16px tall
  const linkClass = (active: boolean) =>
    `inline-flex items-center py-1.5 font-mono text-xs uppercase tracking-wide underline decoration-rule underline-offset-4 ${
      active ? "text-ink decoration-ink" : "text-ink/80 hover:text-ink hover:decoration-ink"
    }`;

  return (
    <div className="border-b-2 border-ink">
      <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-x-6 gap-y-3 px-6 py-4 sm:px-10">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <Link
            href="/dashboard"
            className="inline-flex items-center py-1.5 font-mono text-xs uppercase tracking-wide text-ink/70 underline decoration-rule underline-offset-4 hover:text-ink hover:decoration-ink"
          >
            All leagues
          </Link>
          {leagueName && (
            <span className="font-display text-sm text-ink">{leagueName}</span>
          )}
        </div>

        <nav aria-label="Dashboard sections" className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <Link href={teamHref} aria-current={onTeam ? "page" : undefined} className={linkClass(onTeam)}>
            My Team
          </Link>
          <Link href={draftHref} aria-current={onDraft ? "page" : undefined} className={linkClass(onDraft)}>
            Draft
          </Link>
          <Link href={matchupHref} aria-current={onMatchup ? "page" : undefined} className={linkClass(onMatchup)}>
            Matchup
          </Link>
          {COMING_SOON.map((tool) => (
            <span
              key={tool}
              aria-disabled="true"
              className="inline-flex items-center gap-1.5 font-mono text-xs uppercase tracking-wide text-ink/70"
            >
              {tool}
              <span className="border border-amber px-1 py-0.5 text-[0.6rem] leading-none text-ink/70">
                Soon
              </span>
            </span>
          ))}
          <Link
            href={settingsHref}
            aria-current={onSettings ? "page" : undefined}
            className={linkClass(onSettings)}
          >
            Settings
          </Link>
          <LogoutButton />
        </nav>
      </div>
    </div>
  );
}
