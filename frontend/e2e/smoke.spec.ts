import { test, expect } from "@playwright/test";

// End-to-end smoke test against the real stack (backend + Postgres + frontend
// dev server, all started manually -- see README.md's "E2E smoke test"
// section). Uses the backend's dev-login route (only routable when the
// backend runs with DEV_AUTH_ENABLED=true) to reach an authenticated
// dashboard without a live Yahoo OAuth round trip.

test.describe("landing page", () => {
  test("shows the h1, the Yahoo sign-in CTA, and the Yahoo attribution", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { level: 1, name: "NineCat" })).toBeVisible();

    // the header repeats this same CTA text, so target the hero's by id rather
    // than name alone, which would match both and violate strict mode
    const cta = page.locator("#yahoo-signin-cta");
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute("href", "/api/auth/yahoo/login");

    await expect(page.getByText("Fantasy data provided by Yahoo Fantasy")).toBeVisible();
  });
});

test.describe("dev-login dashboard flow", () => {
  test("dev-login lands on the seeded dev league with roster, build profile, and standings", async ({
    page,
  }) => {
    // page.request shares this test's browser context (and its cookie jar) with
    // page.goto below, so the session cookie the backend sets here is already
    // present on the browser's next navigation -- no separate storageState needed.
    // Hits the rewritten /api path (not the backend origin directly) so the
    // cookie is set for localhost:3000, matching how the real app is used.
    const devLogin = await page.request.post("/api/auth/dev-login");
    expect(devLogin.status()).toBe(204);

    await page.goto("/dashboard");
    // dashboard/page.tsx auto-redirects to /dashboard/{leagueId} once it sees
    // the dev user's single linked league
    await page.waitForURL(/\/dashboard\/\d+$/);

    await expect(page.getByRole("heading", { name: "My Team" })).toBeVisible();

    // roster: a known seeded player renders, and the injured one carries an
    // INJ badge inside its own row (not just visible anywhere on the page)
    await expect(page.getByText("Dev Player One")).toBeVisible();
    const injuredRow = page.getByRole("row", { name: /Dev Player Two/ });
    await expect(injuredRow.getByText("INJ")).toBeVisible();

    // build profile: exactly 9 category cells, one per scoring category, keyed
    // off the table's own caption text ("Category build — mean z-score per category")
    // rather than a fixed index/class so this breaks loudly if categories change
    const buildTable = page.getByRole("table", {
      name: "Category build — mean z-score per category",
    });
    await expect(buildTable.locator("tbody td")).toHaveCount(9);

    // standings: the dev team's own row is present and carries the "Your team" marker
    const standingsRow = page.getByRole("row", { name: /Dev Team/ });
    await expect(standingsRow.getByText("Your team")).toBeVisible();

    // settings: Disconnect/Delete controls are present -- asserted only, never clicked
    const leagueUrl = new URL(page.url());
    await page.goto(`${leagueUrl.pathname}/settings`);
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Disconnect Yahoo" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete account" })).toBeVisible();
  });
});
