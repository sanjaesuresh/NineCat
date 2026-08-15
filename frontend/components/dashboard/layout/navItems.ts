/** Pure nav model for the dashboard sidebar. */

export type NavItem = {
  label: string;
  href: string;
  key: string;
};

/**
 * Builds the six dashboard section entries for a given league. Hrefs follow
 * the dashboard's established URL scheme exactly: the league root for My
 * Team, and the root plus a lowercase segment for the rest.
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
