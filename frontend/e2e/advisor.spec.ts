import { test, expect, type Page } from "@playwright/test";

// End-to-end coverage for the Claude advisor's DEGRADED path
// (docs/claude-advisor-plan.md A2, build plan task 8) -- dev-login only, same
// stack/setup as smoke.spec.ts (see README's "E2E smoke test" section).
//
// Why this spec exists at all: the no-key path is asserted at the endpoint and
// below by the backend suite, but "the product still works and says why" is a
// claim about the rendered page, and only a real page can prove it. The
// backend is started WITHOUT an ANTHROPIC_API_KEY for e2e (the README's
// command sets no such variable), so every one of these pages is exercising
// the mode the vast majority of installs will actually run in.
//
// Deliberately NOT covered here: the explanations-present path. That needs a
// real key and a real API call, and this suite makes neither.

// components/dashboard/advisor/tokens.ts -- the exact copy for the
// "not_configured" token. Asserted verbatim rather than by substring so a
// silent reword of the honesty note fails loudly.
const NOT_CONFIGURED_NOTE =
  "Written explanations are turned off for this install. The ranking below is the engine's own.";

// components/dashboard/advisor/ModelReasoning.tsx -- the attribution marker.
// Nothing on any page may carry it when explanations are off.
const ATTRIBUTION_MARKER = "Claude's read";

async function devLogin(page: Page) {
  const devLogin = await page.request.post("/api/auth/dev-login");
  expect(devLogin.status()).toBe(204);

  await page.goto("/dashboard");
  await page.waitForURL(/\/dashboard\/\d+$/);
  return page.url().match(/\/dashboard\/(\d+)$/)![1];
}

test.describe("advisor degraded path", () => {
  test("draft still recommends, and says explanations are off", async ({ page }) => {
    const leagueId = await devLogin(page);
    await page.goto(`/dashboard/${leagueId}/draft`);

    // the mock-draft panel fetches recommendations on mount for the user's
    // first turn -- the recommendation list appearing IS the deterministic
    // half working with no key configured
    const recommendations = page.getByRole("list", { name: "Top recommendations" });
    await expect(recommendations).toBeVisible();
    await expect(recommendations.locator("li").first()).toBeVisible();

    // the honesty note, verbatim
    await expect(page.getByText(NOT_CONFIGURED_NOTE)).toBeVisible();

    // and no attributed prose anywhere -- an empty explanation block rendering
    // as a bare bordered strip was the failure mode worth pinning
    await expect(page.getByText(ATTRIBUTION_MARKER)).toHaveCount(0);
  });

  test("the note never claims the recommendations themselves are degraded", async ({ page }) => {
    const leagueId = await devLogin(page);
    await page.goto(`/dashboard/${leagueId}/draft`);

    const note = page.getByText(NOT_CONFIGURED_NOTE);
    await expect(note).toBeVisible();

    // the whole point of the copy: explanations are missing, the ranking is
    // not. A note that read as "this page is broken" would be worse than none.
    // Scoped to the note itself rather than the whole page -- a page-wide
    // substring sweep would break on any unrelated future copy containing
    // "error", which would be a false alarm, not a caught regression.
    await expect(note).toContainText("the engine's own");
    const text = ((await note.textContent()) ?? "").toLowerCase();
    for (const alarming of ["error", "failed", "try again", "something went wrong"]) {
      expect(text).not.toContain(alarming);
    }
  });

  test("adds and matchup render their lists with no key configured", async ({ page }) => {
    const leagueId = await devLogin(page);

    for (const tool of ["adds", "matchup"]) {
      await page.goto(`/dashboard/${leagueId}/${tool}`);
      // the page's own heading proves it rendered rather than erroring; the
      // advisor is optional on every one of these
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText(ATTRIBUTION_MARKER)).toHaveCount(0);
      // an unrecognized token would mean the backend emitted a reason this
      // frontend has no copy for -- the exact gap tokens.ts exists to catch
      await expect(page.getByText("unrecognized reason")).toHaveCount(0);
    }
  });
});
