/** Pure nav model for the dashboard sidebar, extracted from DashboardNav.tsx. */

export type NavItem = {
  label: string;
  href: string;
  key: string;
};

/**
 * Builds the six dashboard section entries for a given league. Hrefs mirror
 * DashboardNav.tsx's construction exactly: the league root for My Team, and
 * the root plus a lowercase segment for the rest -- this is a faithful
 * extraction, not a redesign of the URL scheme.
 */
export function buildNavItems(leagueId: string): NavItem[] {
  const root = `/dashboard/${leagueId}`;
  return [
    { label: "My Team", href: root, key: "team" },
    { label: "Draft", href: `${root}/draft`, key: "draft" },
    { label: "Matchup", href: `${root}/matchup`, key: "matchup" },
    { label: "Adds", href: `${root}/adds`, key: "adds" },
    { label: "Trades", href: `${root}/trades`, key: "trades" },
    { label: "Settings", href: `${root}/settings`, key: "settings" },
  ];
}

/**
 * Matches on exact pathname equality only -- if My Team also matched child
 * routes (e.g. the draft path), two links would be marked current at once,
 * which breaks the e2e specs' aria-current="page" assertions.
 */
export function isActiveNavItem(item: NavItem, pathname: string): boolean {
  return pathname === item.href;
}
