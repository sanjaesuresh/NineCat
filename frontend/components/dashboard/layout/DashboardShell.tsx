"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { League } from "@/lib/api";
import Sidebar from "./Sidebar";

/**
 * Two-column dashboard app shell: the Sidebar (fixed 224px on desktop; an
 * off-canvas drawer below 1024px) beside the page content. Desktop collapse
 * was tried and dropped: this design system has no icon set, so a narrower
 * rail still needed full text labels, and the ~96px it saved was invisible
 * above roughly an 1824px viewport once content is capped at 1600px and
 * centered -- not worth the extra state/persistence/toggle surface. The
 * content column is a plain div, not a second <main> -- every child route
 * under app/dashboard/[leagueId] already renders its own <main> (its own
 * horizontal padding; no child route sets its own max-width anymore, since
 * removing those per-page caps was the point of this redesign), so a second
 * <main> landmark here would be an a11y foot-gun (two "main" regions on one
 * page). The capped column only contributes the 1600px width cap; it
 * deliberately does NOT add its own horizontal padding -- every child page
 * still applies its own (its own <main>'s px-*), and adding padding here too
 * would double it. Revisit once pages stop owning their own padding.
 *
 * This is a client component to own the mobile drawer's open/closed state --
 * the single source of truth threaded down into Sidebar as a prop rather
 * than read there directly, so Sidebar stays a plain, prop-driven view of
 * whatever state its parent hands it. The drawer is never persisted; every
 * page load starts closed.
 */
export default function DashboardShell({
  leagueId,
  leagueName,
  leagues,
  leaguesLoaded,
  children,
}: {
  leagueId: string;
  leagueName: string | null;
  leagues: League[];
  leaguesLoaded: boolean;
  children: ReactNode;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  // closing the drawer must always return focus to the control that opened
  // it (WCAG 2.4.3) -- kept as a ref here, not state, since it never needs
  // to trigger a re-render
  const triggerRef = useRef<HTMLButtonElement>(null);
  // set by a user-initiated close (Escape, backdrop click, nav-link
  // activation) so the effect below knows to return focus; a breakpoint
  // crossing force-close is not a "close" gesture and must not steal focus
  const restoreFocusOnCloseRef = useRef(false);

  // stable across renders (empty deps -- setDrawerOpen is a stable setState
  // identity and the ref is a stable object) so it's safe as a dependency of
  // Sidebar's trap effect: previously this was redefined every render,
  // which re-ran that effect -- and re-fired its initial-focus call -- on
  // every unrelated parent re-render (e.g. the layout's getMe resolution,
  // which commits state twice)
  const closeDrawer = useCallback(() => {
    restoreFocusOnCloseRef.current = true;
    setDrawerOpen(false);
  }, []);

  // the drawer breakpoint must never rise above 1024px (see e2e/shell.spec
  // and the four section specs, which all rely on all six links staying
  // visible+clickable at the 1280px default viewport) -- 1024px matches
  // Tailwind's default `lg:` used throughout this file/Sidebar, so a resize
  // that crosses it forces the drawer closed in the one place both the
  // backdrop's CSS and Sidebar's focus trap read from, rather than leaving
  // React state open with a display:none backdrop and a live trap listener
  // (WCAG 2.1.2 keyboard trap)
  useEffect(() => {
    const query = window.matchMedia("(min-width: 1024px)");
    function handleChange(event: MediaQueryListEvent | MediaQueryList) {
      if (!event.matches) return;
      // this is a forced close, not a user close gesture, and must never
      // steal focus (see the comment on the ref's declaration above) --
      // cleared here rather than trusting the flag to already be false,
      // since closeDrawer() could in principle have set it true while the
      // drawer was already closed (a no-op setDrawerOpen(false) that never
      // reaches the effect below to clear it), stranding it true for a
      // later close that must NOT restore focus
      restoreFocusOnCloseRef.current = false;
      setDrawerOpen(false);
    }
    handleChange(query);
    query.addEventListener("change", handleChange);
    return () => query.removeEventListener("change", handleChange);
  }, []);

  // makes the open drawer genuinely modal to assistive tech: `inert` pulls
  // the site header and content column out of both the accessibility tree
  // and the tab order in one step, which a Tab-key trap alone doesn't do (a
  // screen reader's virtual cursor walks the a11y tree independent of tab
  // order). The content column is owned by this component and gets `inert`
  // directly as a prop below; the persistent site header is rendered once
  // in the root layout, outside this subtree, so it's reached here via
  // query instead. The trigger bar is never touched by either of those and
  // stays fully focusable/interactive throughout: it lives in its own
  // `lg:hidden` bar, a sibling of the content column, not a descendant of
  // it, so neither the content column's `inert` prop nor the header/footer
  // query below ever reaches it.
  useEffect(() => {
    if (!drawerOpen) return;
    const outside = document.querySelectorAll<HTMLElement>("body > header, body > footer");
    outside.forEach((el) => el.setAttribute("inert", ""));
    return () => outside.forEach((el) => el.removeAttribute("inert"));
  }, [drawerOpen]);

  // deferred to an effect (not called synchronously in the close handler)
  // because closing flips the drawer's `<aside>` to `display:none` (see
  // Sidebar's `hidden`/`flex` toggle), and removing whatever currently has
  // focus from the render tree unavoidably blows focus back to `<body>` as
  // a side effect of that DOM change. A synchronous `.focus()` call inside
  // the click/Escape handler would run *before* React commits that
  // display:none change, so the browser's own focus-reset would simply
  // clobber it a moment later. Running in an effect keyed on `drawerOpen`
  // guarantees this call happens after that commit, so it's the last word.
  useEffect(() => {
    if (drawerOpen || !restoreFocusOnCloseRef.current) return;
    restoreFocusOnCloseRef.current = false;
    triggerRef.current?.focus();
  }, [drawerOpen]);

  // background scroll lock while the drawer is open below the breakpoint --
  // without this, `aria-modal="true"` on the drawer is a half-truth: the
  // page behind it is still scrollable. Reading/restoring the previous
  // inline value (rather than always clearing to "") means this doesn't
  // clobber some other future consumer of body.style.overflow. The cleanup
  // runs on every path that ends the open state -- explicit close, the
  // breakpoint force-close above, and unmount -- since all of them are just
  // `drawerOpen` transitioning away from `true`/the effect tearing down.
  useEffect(() => {
    if (!drawerOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [drawerOpen]);

  return (
    <div className="w-full">
      {/* mobile-only trigger bar -- `lg:hidden` because at 1024px+ the
          sidebar is always laid out in the grid and this control has
          nothing to do. Open-only: the drawer's backdrop covers this button
          for pointer input and the focus trap never lets keyboard focus
          reach it while open, so a click/Enter here while already open
          would be unreachable dead code -- closing happens via Escape or
          the drawer's own visible close button (see Sidebar.tsx) instead.
          Deliberately NOT `inert` while the drawer is open: nothing here
          actually depends on that (see the inert effect's comment above),
          and leaving it interactive keeps `aria-expanded` meaningful */}
      <div className="flex items-center border-b border-rule bg-paper px-4 py-3 lg:hidden">
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-expanded={drawerOpen}
          aria-controls="dashboard-sidebar"
          className="inline-flex items-center gap-2 border border-ink-muted px-3 py-1.5 font-mono text-xs uppercase tracking-wide text-ink hover:border-ink"
        >
          <span aria-hidden="true">≡</span>
          <span className="sr-only">Open navigation</span>
        </button>
      </div>

      <div className="flex w-full">
        {drawerOpen && (
          // covers the content column so a mouse click outside the drawer
          // closes it too, not just Escape; `lg:hidden` so a drawer left
          // open in React state before a resize to desktop width can never
          // paint an inert-looking backdrop over the (now always-visible,
          // fully interactive) desktop rail. --ink-fill is the documented
          // general dark-fill token (same value as the --espresso pair
          // reserved for AuthErrorNotice, which this isn't)
          <div
            className="fixed inset-0 z-40 bg-ink-fill/70 lg:hidden"
            onClick={closeDrawer}
            aria-hidden="true"
          />
        )}

        <Sidebar
          leagueId={leagueId}
          leagueName={leagueName}
          leagues={leagues}
          leaguesLoaded={leaguesLoaded}
          drawerOpen={drawerOpen}
          onCloseDrawer={closeDrawer}
        />
        <div className="mx-auto min-w-0 w-full max-w-[1600px]" inert={drawerOpen}>
          {children}
        </div>
      </div>
    </div>
  );
}
