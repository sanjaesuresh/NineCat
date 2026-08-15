import { test, expect, type Page } from "@playwright/test";

// Coverage for the responsive sidebar shell (Task 5): the desktop rail stays
// fully visible and clickable at the suite's default 1280x720 viewport (see
// draft/adds/matchup/trades.spec.ts, which all click these same six links --
// this spec exists to pin the breakpoint that protects them), and collapses
// into an off-canvas drawer with a trap below 1024px. Same dev-login setup
// pattern as smoke.spec.ts / adds.spec.ts.

const SIX_NAV_LABELS = ["My Team", "Draft", "Matchup", "Adds", "Trades", "Settings"];
const MOBILE_VIEWPORT = { width: 375, height: 800 };

async function devLogin(page: Page) {
  const devLogin = await page.request.post("/api/auth/dev-login");
  expect(devLogin.status()).toBe(204);

  await page.goto("/dashboard");
  await page.waitForURL(/\/dashboard\/\d+$/);
}

// asserts each of the six links genuinely exists in the closed drawer's DOM
// (a positive count, via `includeHidden` since a plain role query excludes
// display:none elements from the accessibility tree entirely -- resolving
// to zero matches would make a bare `.not.toBeVisible()` pass for the wrong
// reason) AND that it's actually hidden, not just off-screen
async function expectDrawerLinksHidden(page: Page) {
  for (const label of SIX_NAV_LABELS) {
    const link = page.getByRole("link", { name: label, exact: true, includeHidden: true });
    await expect(link).toHaveCount(1);
    await expect(link).not.toBeVisible();
  }
}

test.describe("dashboard shell", () => {
  test("at the default desktop viewport, all six nav links are visible and directly clickable", async ({
    page,
  }) => {
    await devLogin(page);

    for (const label of SIX_NAV_LABELS) {
      await expect(page.getByRole("link", { name: label, exact: true })).toBeVisible();
    }

    // the drawer trigger renders at every viewport (it's `display:none` via
    // `lg:hidden`, not conditionally rendered) -- at 1280px it's excluded
    // from the accessibility tree by that display:none, which is why a
    // plain role query finds zero matches; `includeHidden` proves it's
    // present-but-hidden rather than absent
    await expect(page.getByRole("button", { name: "Open navigation" })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Open navigation", includeHidden: true }),
    ).toHaveCount(1);

    await page.getByRole("link", { name: "Draft", exact: true }).click();
    await page.waitForURL(/\/dashboard\/\d+\/draft$/);

    await expect(page.getByRole("link", { name: "Draft", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.getByRole("link", { name: "My Team", exact: true })).not.toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("below 1024px, the nav is a drawer opened by the trigger and closed by Escape, returning focus", async ({
    page,
  }) => {
    await devLogin(page);
    await page.setViewportSize(MOBILE_VIEWPORT);

    const trigger = page.getByRole("button", { name: "Open navigation" });
    await expect(trigger).toBeVisible();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

    // closed by default: none of the six links are visible (they're
    // display:none off-canvas, not just scrolled out of view), and the site
    // header/footer aren't inert yet -- baseline for the inert assertions
    // below
    await expectDrawerLinksHidden(page);
    // `body > header` mirrors DashboardShell's own `body > header, body >
    // footer` query -- a bare `header` locator would also match PageHeader's
    // (non-direct-child) header once that component is wired into every
    // dashboard page, tripping Playwright strict mode for a reason unrelated
    // to what this test asserts
    const header = page.locator("body > header");
    const footer = page.locator("body > footer");
    await expect(header).not.toHaveAttribute("inert");
    await expect(footer).not.toHaveAttribute("inert");

    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    for (const label of SIX_NAV_LABELS) {
      await expect(page.getByRole("link", { name: label, exact: true })).toBeVisible();
    }
    // opening moves focus to the drawer's first focusable element (the
    // wordmark link), not left behind on the trigger
    await expect(page.getByRole("link", { name: "NINECAT All leagues" })).toBeFocused();
    // genuinely modal to assistive tech, not just visually on top
    await expect(page.locator("#dashboard-sidebar")).toHaveAttribute("role", "dialog");
    await expect(page.locator("#dashboard-sidebar")).toHaveAttribute("aria-modal", "true");

    // the persistent site header and footer must be genuinely inert while
    // the drawer is open, not just visually covered. `inert` is applied via
    // a CSS-selector query against markup app/layout.tsx owns
    // (Sidebar.tsx/DashboardShell.tsx don't render the header/footer
    // themselves), the most brittle wiring in this component -- its failure
    // mode is a silent no-op, and nothing else in the suite exercises it.
    // (Tried asserting the sign-in link's absence from the accessibility
    // tree instead, which is the more behavioral proof -- but Playwright's
    // own role/visibility queries in this version don't factor `inert` into
    // either, so that assertion passed even against a header that was never
    // actually inert-ed; confirmed by reading the `inert` attribute directly
    // via `page.evaluate` during investigation. Asserting the attribute
    // itself is the one that's actually discriminating here. The footer gets
    // the same assertion since the production query covers both, and a
    // refactor that wrapped only the footer would otherwise silently stop
    // inerting it with no test failure.)
    await expect(header).toHaveAttribute("inert", "");
    await expect(footer).toHaveAttribute("inert", "");

    await page.keyboard.press("Escape");

    await expectDrawerLinksHidden(page);
    await expect(trigger).toBeFocused();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    // inert lifted again once the drawer closes -- the site header and
    // footer are reachable again
    await expect(header).not.toHaveAttribute("inert");
    await expect(footer).not.toHaveAttribute("inert");
  });

  test("the drawer's visible close button closes it and returns focus to the trigger", async ({
    page,
  }) => {
    await devLogin(page);
    await page.setViewportSize(MOBILE_VIEWPORT);

    const trigger = page.getByRole("button", { name: "Open navigation" });
    await trigger.click();
    for (const label of SIX_NAV_LABELS) {
      await expect(page.getByRole("link", { name: label, exact: true })).toBeVisible();
    }

    // the trigger itself has no reachable close affordance once open (the
    // backdrop covers it for pointer input, and the focus trap never lets
    // keyboard focus reach it) -- this in-drawer button is the only
    // reachable non-Escape close path, exercised here as the real gesture a
    // pointer or keyboard user would use
    const closeButton = page.getByRole("button", { name: "Close navigation" });
    await expect(closeButton).toBeVisible();
    await closeButton.click();

    await expectDrawerLinksHidden(page);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(trigger).toBeFocused();
  });

  test("Tab wraps at both trap boundaries instead of leaking focus out of the drawer", async ({
    page,
  }) => {
    await devLogin(page);
    await page.setViewportSize(MOBILE_VIEWPORT);

    await page.getByRole("button", { name: "Open navigation" }).click();

    const firstFocusable = page.getByRole("link", { name: "NINECAT All leagues" });
    const lastFocusable = page.getByRole("button", { name: "Log out" });

    await lastFocusable.focus();
    await expect(lastFocusable).toBeFocused();

    await page.keyboard.press("Tab");
    await expect(firstFocusable).toBeFocused();

    await page.keyboard.press("Shift+Tab");
    await expect(lastFocusable).toBeFocused();
  });

  test("activating a nav link inside the drawer closes it and returns focus to the trigger", async ({
    page,
  }) => {
    await devLogin(page);
    await page.setViewportSize(MOBILE_VIEWPORT);

    const trigger = page.getByRole("button", { name: "Open navigation" });
    await trigger.click();
    await expect(page.getByRole("link", { name: "Draft", exact: true })).toBeVisible();

    await page.getByRole("link", { name: "Draft", exact: true }).click();
    await page.waitForURL(/\/dashboard\/\d+\/draft$/);

    // the drawer must not survive the navigation and cover the destination
    // page (this is the drawer's most common close path)
    await expectDrawerLinksHidden(page);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(trigger).toBeFocused();
  });

  test("crossing the breakpoint with the drawer open force-closes it and drops the keyboard trap", async ({
    page,
  }) => {
    await devLogin(page);
    await page.setViewportSize({ width: 834, height: 900 });

    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.getByRole("link", { name: "Draft", exact: true })).toBeVisible();

    // rotate/resize across the 1024px boundary while the drawer is open
    await page.setViewportSize({ width: 1194, height: 900 });

    // state is reset, not just visually overridden by the desktop CSS
    await expect(
      page.getByRole("button", { name: "Open navigation", includeHidden: true }),
    ).toHaveAttribute("aria-expanded", "false");

    // no keyboard trap remains: Shift+Tab from the rail's first focusable
    // element must leave the aside entirely (landing on SiteHeader's own
    // sign-in link, which -- unlike anything on the dashboard page below --
    // is guaranteed to render on every route) rather than wrap back to the
    // last element the way the trap used to
    await page.getByRole("link", { name: "NINECAT All leagues" }).focus();
    await page.keyboard.press("Shift+Tab");
    const focusEscapedDrawer = await page.evaluate(
      () => document.activeElement?.closest("#dashboard-sidebar") == null,
    );
    expect(focusEscapedDrawer).toBe(true);
    await expect(page.getByRole("link", { name: "Sign in with Yahoo" })).toBeFocused();

    // and the drawer doesn't reopen stuck-open the next time the viewport
    // drops back below the breakpoint
    await page.setViewportSize(MOBILE_VIEWPORT);
    await expectDrawerLinksHidden(page);
  });
});
