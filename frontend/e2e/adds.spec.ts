import { test, expect, type Page } from "@playwright/test";

// End-to-end coverage for the Adds page (docs/waiver-valuation-plan.md) --
// dev-login only, no live Yahoo access, same conventions as matchup.spec.ts.
//
// An empty candidate list is a legitimate answer on this page (the engine's
// worth-it gate DROPS candidates that don't actually help rather than ranking
// them last), so the assertions below accept either the ranked table or the
// honest empty state -- but never a silently blank section.

const FORBIDDEN_RAW_TOKENS = [
  "fg_pct",
  "ft_pct",
  "tov",
  "tpm",
  "schedule_driven",
  "season_average_fallback",
  "no_games_in_window",
  "no_candidates",
  "no_close_categories",
  "no_adds_available",
  "invalid_window",
  "no_positive_value_remaining",
];

async function devLoginAndOpenAddsTab(page: Page) {
  const devLogin = await page.request.post("/api/auth/dev-login");
  expect(devLogin.status()).toBe(204);

  await page.goto("/dashboard");
  await page.waitForURL(/\/dashboard\/\d+$/);

  const addsLink = page.getByRole("link", { name: "Adds", exact: true });
  await expect(addsLink).toBeVisible();
  await expect(page.getByText("Soon")).toHaveCount(0);

  await addsLink.click();
  await page.waitForURL(/\/dashboard\/\d+\/adds$/);
}

test.describe("adds", () => {
  test("dev-login reaches the adds page via a real nav link", async ({ page }) => {
    await devLoginAndOpenAddsTab(page);

    await expect(page.getByRole("heading", { name: "Adds", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Adds", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("week context, ranking basis, and candidates all render honestly", async ({ page }) => {
    await devLoginAndOpenAddsTab(page);

    // --- week context: which week, and whether its dates were derived ------
    await expect(page.getByText(/Week \d+ ·/)).toBeVisible();
    await expect(page.getByText(/Data as of /)).toBeVisible();

    // the seeded demo week is never the real current week (it's pinned to a
    // fixed fantasy week of the configured season), so the page must say so --
    // which direction depends on today's real date, so accept either honest copy
    await expect(
      page.getByRole("status").filter({ hasText: /already ended|hasn't started yet/ }),
    ).toBeVisible();

    // --- ranking basis: what this list is actually optimizing for ----------
    const basisSection = page.locator("section:has(#basis-heading)");
    await expect(basisSection).toBeVisible();
    // one of the three legitimate states -- targeting close categories, no
    // close categories, or no opponent at all -- never a blank panel
    await expect(
      basisSection
        .getByText(/Targeting the categories close in this week's matchup:/)
        .or(basisSection.getByText(/No categories in this week's matchup are close enough/))
        .or(basisSection.getByText(/Ranking by roster need only/)),
    ).toBeVisible();

    // --- candidates: the ranked table, or the honest "nothing is worth an
    // add" state, or the schedule-coverage replacement --------------------
    const candidateSection = page.locator("section:has(#candidates-heading)");
    await expect(candidateSection).toBeVisible();
    const table = candidateSection.getByRole("table", {
      name: /Available free agents ranked by projected value/,
    });
    if ((await table.count()) > 0) {
      await expect(table).toBeVisible();
      const rows = table.locator("tbody tr");
      expect(await rows.count()).toBeGreaterThan(0);
      // rank column is a real 1..n sequence, so the list is ordered rather
      // than an arbitrary dump
      const ranks = (await table.locator("tbody tr td:first-child").allInnerTexts()).map((t) =>
        Number(t.trim()),
      );
      expect(ranks).toEqual(ranks.map((_, i) => i + 1));
    } else {
      await expect(
        candidateSection
          .getByText(/No free agent on the wire actually helps this roster this week/)
          .or(candidateSection.getByText(/schedule/i)),
      ).toBeVisible();
    }

    // --- no raw contract keys or bare tokens anywhere on the rendered page --
    const pageText = await page.locator("body").innerText();
    for (const token of FORBIDDEN_RAW_TOKENS) {
      expect(pageText).not.toContain(token);
    }
  });

  // WP5: the dev league never gets a synced free-agent snapshot (no linked
  // Yahoo token), so its adds response is always pool_basis "draftable_pool"
  // -- this is the one basis this stack can honestly e2e without a real
  // Yahoo token. Live-basis UI (the real free-agent note, the "Refresh free
  // agents" action) is unverifiable here; see WP5 plan verification notes.
  test("dev league's draftable-pool basis shows the demo-pool note with no refresh action", async ({
    page,
  }) => {
    await devLoginAndOpenAddsTab(page);

    await expect(
      page.getByText(/Candidates come from a seeded demo pool of draftable players/),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh free agents" })).toHaveCount(0);
  });
});
