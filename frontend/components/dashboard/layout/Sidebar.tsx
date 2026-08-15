"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { League } from "@/lib/api";
import { formatSyncedAt } from "@/components/dashboard/format";
import LogoutButton from "@/components/dashboard/LogoutButton";
import { buildNavItems, isActiveNavItem } from "./navItems";
import { buildLeagueOptions } from "./leagueOptions";

// selector for the trap/initial-focus queries below -- covers every element
// this rail can realistically contain: links, the rail's non-link buttons
// (LogoutButton and the drawer's own close button), the league <select>,
// and any future form control, plus the categories WCAG-focus-order
// guidance calls out: text inputs, textareas, <summary>, and
// contenteditable regions
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]), textarea:not([disabled]), summary, [contenteditable]:not([contenteditable="false"]), [tabindex]:not([tabindex="-1"])';

// `offsetParent` is null for display:none elements (and reads null in a few
// other edge cases none of this rail's descendants hit -- none are
// `position: fixed` themselves, only the <aside> ancestor is) -- cheap way
// to exclude elements that are only display:none at the current breakpoint
// by accident of DOM ordering rather than intentionally hidden
function isVisible(el: HTMLElement): boolean {
  return el.offsetParent !== null;
}

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    isVisible,
  );
}

/**
 * Left rail for a single-league dashboard: wordmark, league switcher, the
 * six section links, then a footer with last-synced + logout. One instance
 * serves two responsive presentations, never two separate DOM copies (that
 * would double up the "Dashboard sections" nav and break aria-current
 * lookups):
 *   - >=1024px (`lg:`): always laid out inline in DashboardShell's flex row,
 *     `lg:sticky` pinning it to the viewport, fixed at 224px (`lg:w-56`).
 *     No collapse -- a narrower rail was tried and dropped (see
 *     DashboardShell's docstring for why) -- the rail's width never changes
 *     at this breakpoint and up.
 *   - <1024px: an off-canvas drawer, genuinely modal to assistive tech while
 *     open (`role="dialog"` + `aria-modal`, only applied while `drawerOpen`
 *     -- at >=1024px this reverts to the plain `<aside>`'s implicit
 *     "complementary" landmark). `hidden`/`flex` (not a transform) drives
 *     visibility, toggled by `drawerOpen` -- Playwright's visibility check
 *     only inspects computed display/visibility/size, not on/off-screen
 *     position, so a translate-based slide would still read as "visible"
 *     while closed. `lg:flex` unconditionally overrides `hidden` at the
 *     breakpoint, matching "drawer state is irrelevant at 1024px+." Because
 *     `display:none` also removes the element from the tab order and a11y
 *     tree for free, the closed drawer needs no extra `inert`/`aria-hidden`
 *     wiring; DashboardShell handles inert-ing everything *outside* the open
 *     drawer (the trigger bar, content column, and the persistent site
 *     header/footer).
 * `max-h-screen` + `overflow-y-auto` only ever kicks in its own scroll
 * region if the rail's own content (unusually many leagues, say) exceeds the
 * viewport -- it does NOT force a fixed full-height box, which used to push
 * the footer below the fold on short viewports. `<aside>` (not a plain div)
 * because this is a persistent site-level complementary landmark; the inner
 * `<nav aria-label="Dashboard sections">` is the actual six-link navigation
 * region and stays as-is.
 */
export default function Sidebar({
  leagueId,
  leagueName,
  leagues,
  leaguesLoaded,
  drawerOpen,
  onCloseDrawer,
}: {
  leagueId: string;
  leagueName: string | null;
  leagues: League[];
  leaguesLoaded: boolean;
  /** Mobile-only; ignored once `lg:` forces the rail permanently visible. */
  drawerOpen: boolean;
  onCloseDrawer: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const asideRef = useRef<HTMLElement>(null);
  const navItems = buildNavItems(leagueId);
  const leagueOptions = buildLeagueOptions({ leagueId, leagueName, leagues, leaguesLoaded });
  const currentLeague = leagues.find((l) => String(l.id) === leagueId) ?? null;

  // the <select>'s own DOM value tracks the user's in-progress arrow-key/
  // mouse selection; navigation itself only fires on blur/Enter (see below),
  // not on every change event -- committing on change fires once per option
  // an arrow-keying keyboard user passes over, each a real navigation
  // (WCAG 3.2.2 On Input)
  const [pendingLeagueId, setPendingLeagueId] = useState(leagueId);
  // resync pendingLeagueId when the route's leagueId changes underneath us
  // (e.g. browser back/forward) -- adjusted during render, not in an effect,
  // per React's "adjusting state when a prop changes" pattern, so this
  // doesn't cost an extra commit+effect pass
  const [syncedLeagueId, setSyncedLeagueId] = useState(leagueId);
  if (leagueId !== syncedLeagueId) {
    setSyncedLeagueId(leagueId);
    setPendingLeagueId(leagueId);
  }

  function commitLeagueChange(nextLeagueId: string) {
    if (nextLeagueId !== leagueId) {
      // the target route stays inside this same layout (DashboardShell never
      // unmounts across a league switch), so nothing else closes the drawer
      // for us here -- unlike the wordmark link, which only avoids this bug
      // by the accident of navigating to /dashboard and unmounting the shell
      if (drawerOpen) onCloseDrawer();
      router.push(`/dashboard/${nextLeagueId}`);
    }
  }

  // inline-flex + py-1.5 pads each link's hit area to a ~24px target (WCAG
  // 2.2 2.5.8), preserved verbatim from DashboardNav.tsx's linkClass
  const linkClass = (active: boolean) =>
    `inline-flex items-center py-1.5 font-mono text-xs uppercase tracking-wide underline decoration-rule underline-offset-4 ${
      active ? "text-ink decoration-ink" : "text-ink/80 hover:text-ink hover:decoration-ink"
    }`;

  // moves focus to the drawer's first focusable element exactly once per
  // open transition -- split out from the keydown-listener effect below so
  // a parent re-render that merely creates a new (but equal-value)
  // `drawerOpen` doesn't re-run this and yank focus back to the top; only an
  // actual false->true transition should steal focus
  useEffect(() => {
    if (!drawerOpen) return;
    const node = asideRef.current;
    if (!node) return;
    getFocusableElements(node)[0]?.focus();
  }, [drawerOpen]);

  // focus trap + Escape-to-close, wired up only while the mobile drawer is
  // actually open -- the always-visible desktop rail never runs this, and a
  // closed drawer needs nothing here since `display:none` already drops it
  // out of the tab order. Only the two boundary cases (Tab on the last
  // focusable, Shift+Tab on the first) are intercepted; every other Tab
  // press already stays inside the aside because its focusable descendants
  // are contiguous in the DOM -- this is the standard minimal trap, not a
  // hand-rolled substitute for a library. Recomputes the focusable list on
  // every keydown (not once at effect setup) since the league <select>'s
  // option count / disabled state can change without the effect re-running.
  useEffect(() => {
    if (!drawerOpen) return;
    const node = asideRef.current;
    if (!node) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseDrawer();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const focusables = getFocusableElements(node);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    node.addEventListener("keydown", onKeyDown);
    return () => node.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen, onCloseDrawer]);

  return (
    <aside
      ref={asideRef}
      id="dashboard-sidebar"
      role={drawerOpen ? "dialog" : undefined}
      aria-modal={drawerOpen ? "true" : undefined}
      aria-label={drawerOpen ? "Dashboard navigation" : undefined}
      className={`${drawerOpen ? "flex" : "hidden"} fixed top-0 bottom-0 left-0 z-50 max-h-screen w-56 shrink-0 flex-col overflow-y-auto border-r-2 border-ink bg-paper px-5 py-6 lg:sticky lg:bottom-auto lg:left-auto lg:z-auto lg:flex lg:w-56`}
    >
      <div className="flex items-center justify-between gap-2">
        <Link
          href="/dashboard"
          className="font-display text-lg uppercase tracking-[0.01em] text-ink no-underline transition-opacity hover:opacity-80 focus-visible:opacity-80"
        >
          NINE<span className="text-red-ink">CAT</span>
          {/* accessible name must contain the visible label (WCAG 2.5.3) --
              appending rather than replacing keeps this link's name distinct
              from the site header's own "NINECAT" link */}
          <span className="sr-only"> All leagues</span>
        </Link>
        {/* the drawer's own visible close control (mobile only, via the
            drawerOpen guard -- never rendered on the always-visible desktop
            rail). The trigger button in DashboardShell can no longer close
            the drawer itself: the backdrop covers it for pointer input and
            the focus trap below never lets keyboard focus reach it, so an
            in-drawer control is the only reachable way to close without
            Escape. Placed right after the wordmark (not before it, and not
            after the last focusable element) so it doesn't change which
            element is first/last in the trap -- those are what the
            Tab-wraparound test asserts against. */}
        {drawerOpen && (
          <button
            type="button"
            onClick={onCloseDrawer}
            className="inline-flex items-center border border-ink-muted px-2 py-1 font-mono text-xs uppercase tracking-wide text-ink hover:border-ink"
          >
            <span aria-hidden="true">×</span>
            <span className="sr-only">Close navigation</span>
          </button>
        )}
      </div>

      <div className="mt-6">
        <label
          htmlFor="league-switcher"
          className="font-mono text-[11px] uppercase tracking-wide text-ink-muted"
        >
          League
        </label>
        <select
          id="league-switcher"
          value={pendingLeagueId}
          onChange={(event) => setPendingLeagueId(event.target.value)}
          onBlur={(event) => commitLeagueChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") commitLeagueChange(event.currentTarget.value);
          }}
          className="mt-1 w-full border border-ink-muted bg-transparent px-2 py-1.5 font-body text-sm text-ink"
        >
          {leagueOptions.map((league) => (
            <option key={league.id} value={league.id} disabled={league.disabled}>
              {league.name}
            </option>
          ))}
        </select>
      </div>

      <nav aria-label="Dashboard sections" className="mt-6 flex flex-col gap-1">
        {navItems.map((item) => {
          const active = isActiveNavItem(item, pathname);
          return (
            <Link
              key={item.key}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={linkClass(active)}
              // the drawer must not survive a client-side navigation to the
              // destination page (see the module docstring); at >=1024px
              // `drawerOpen` is always false so this never fires there
              onClick={drawerOpen ? onCloseDrawer : undefined}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-6 border-t border-rule pt-3">
        <p className="font-mono text-[11px] uppercase tracking-wide text-ink-muted">
          {currentLeague ? `Synced ${formatSyncedAt(currentLeague.synced_at)}` : "Synced —"}
        </p>
        <div className="mt-2">
          <LogoutButton />
        </div>
      </div>
    </aside>
  );
}
