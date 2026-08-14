import { test, expect, type Page } from "@playwright/test";

// End-to-end coverage for the Draft Assistant (docs/draft-assistant-plan.md,
// Phase 2 T8) -- dev-login only, no live Yahoo access, same stack/setup as
// smoke.spec.ts (see README's "E2E smoke test" section). Follows that spec's
// conventions: page.request for dev-login (shares the browser context's cookie
// jar with page.goto below), role-based locators keyed off accessible names
// and table captions, and assertions against known seeded data/exact backend
// contract strings rather than brittle CSS/index selectors.

// formatSignedNumber (components/dashboard/format.ts) renders "+12.34" / "−1.23"
// using U+2212 MINUS SIGN, not a hyphen -- normalize before parsing to a number.
function parseSignedNumber(text: string): number {
  return Number(text.replace("−", "-").replace("+", "").trim());
}

async function devLoginAndOpenDraftTab(page: Page) {
  const devLogin = await page.request.post("/api/auth/dev-login");
  expect(devLogin.status()).toBe(204);

  await page.goto("/dashboard");
  // dashboard/page.tsx auto-redirects to /dashboard/{leagueId} once it sees
  // the dev user's single linked league (same as smoke.spec.ts)
  await page.waitForURL(/\/dashboard\/\d+$/);

  // prove the Draft tab is a real link. Every tool is unlocked now (Trades
  // was the last coming-soon badge), so the original "a Soon chip still
  // exists" companion assertion is replaced by the whole link set: that keeps
  // the intent -- proving DashboardNav actually renders its tools as links --
  // rather than proving one <a> happens to exist.
  const draftLink = page.getByRole("link", { name: "Draft", exact: true });
  await expect(draftLink).toBeVisible();
  for (const tool of ["My Team", "Matchup", "Adds", "Trades"]) {
    await expect(page.getByRole("link", { name: tool, exact: true })).toBeVisible();
  }
  await expect(page.getByText("Soon")).toHaveCount(0);

  await draftLink.click();
  await page.waitForURL(/\/dashboard\/\d+\/draft$/);
}

test.describe("draft assistant", () => {
  test("dev-login reaches the draft page via a real nav link", async ({ page }) => {
    await devLoginAndOpenDraftTab(page);

    await expect(page.getByRole("heading", { name: "Draft", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Draft", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("big board renders seeded players, ranked by value, with Jokic near the top", async ({
    page,
  }) => {
    await devLoginAndOpenDraftTab(page);

    // caption text is BigBoardTable's sr-only accessible name -- same
    // pattern smoke.spec.ts uses for the build-profile table lookup
    const board = page.getByRole("table", {
      name: "Draftable players ranked by value, with per-category z-scores",
    });
    await expect(board).toBeVisible();

    const rows = board.locator("tbody tr");
    const rowCount = await rows.count();
    // ~72-player dev-seed draftable pool (backend/src/ninecat/auth/routes.py) --
    // a generous floor that proves this is a real pool, not an empty/stub board
    expect(rowCount).toBeGreaterThan(20);

    // ordering property, not an exact row list (per T6's reviewed lesson: a
    // regression guard must exercise the real ranking signal): the Value
    // column (4th td) must be sorted non-increasing top to bottom
    const valueTexts = await board.locator("tbody tr td:nth-child(4)").allInnerTexts();
    const values = valueTexts.map(parseSignedNumber);
    for (let i = 1; i < values.length; i++) {
      expect(values[i]).toBeLessThanOrEqual(values[i - 1]);
    }

    // known elite seeded player (id 900101, first row of the dev seed's
    // draftable pool) should rank at or near the top, not buried in the pool
    const jokicRow = board.getByRole("row", { name: /Nikola Jokic/ });
    await expect(jokicRow).toBeVisible();
    const jokicRank = Number((await jokicRow.locator("td").first().innerText()).trim());
    expect(jokicRank).toBeLessThanOrEqual(5);
  });

  test("applying a punt suggestion re-ranks the board; clearing it restores the board", async ({
    page,
  }) => {
    await devLoginAndOpenDraftTab(page);

    const board = page.getByRole("table", {
      name: "Draftable players ranked by value, with per-category z-scores",
    });
    // re-resolved on every call so it always reads Jokic's CURRENT row,
    // regardless of where punt-adjusted re-ranking places him
    const jokicValueCell = () =>
      board.getByRole("row", { name: /Nikola Jokic/ }).locator("td").nth(3);

    const baselineValue = (await jokicValueCell().innerText()).trim();

    const puntSection = page.locator("section:has(#punt-heading)");
    // scope to the first suggestion card's own button by position, not by
    // accessible name -- the name flips to "Applied — clear" on click, so a
    // name-based query would silently re-resolve to a DIFFERENT card's button
    const firstPuntCard = puntSection.locator("li").first();
    const applyButton = firstPuntCard.getByRole("button");
    await expect(applyButton).toHaveText("Apply this punt");
    await applyButton.click();

    // board is marked punt-adjusted...
    const boardSection = page.locator("section:has(#board-heading)");
    await expect(boardSection.getByText(/Board adjusted for punt:/)).toBeVisible();
    const clearBannerButton = boardSection.getByRole("button", { name: "Clear punt" });
    await expect(clearBannerButton).toBeVisible();
    await expect(applyButton).toHaveText("Applied — clear");
    await expect(applyButton).toHaveAttribute("aria-pressed", "true");

    // ...and the board visibly re-ranks: Jokic's own value changes once a
    // category's z-score is excluded from his total (a real, healthy elite
    // player carries a nonzero z in every one of the 9 categories, so this
    // always moves regardless of which category got punted)
    await expect(jokicValueCell()).not.toHaveText(baselineValue);

    // clear the punt: draft/page.tsx reuses the unpunted baseBoard client-side
    // (no round trip), so the board must return exactly to its prior state
    await clearBannerButton.click();
    await expect(boardSection.getByText(/Board adjusted for punt:/)).toHaveCount(0);
    await expect(applyButton).toHaveText("Apply this punt");
    await expect(jokicValueCell()).toHaveText(baselineValue);
  });

  test("mock draft: starting a session and making a pick surfaces a recommendation with a reason", async ({
    page,
  }) => {
    await devLoginAndOpenDraftTab(page);

    await expect(
      page.getByRole("heading", { name: "Mock draft & recommendations" }),
    ).toBeVisible();
    const sessionSection = page.locator("section:has(#session-heading)");

    // explicit (re)start -- DraftSessionPanel also fetches on mount, but this
    // proves the reset control genuinely starts a fresh session
    await sessionSection.getByRole("button", { name: "Reset mock draft" }).click();

    // recommendation cards render as <li> inside a list with its own
    // accessible name -- scoping through it (not just "first li in the
    // section") matters once a pick has been made, since the opponent-log
    // list ("Since your last turn") also renders <li> items above it
    const recommendationList = sessionSection.getByRole("list", { name: "Top recommendations" });
    const firstCard = recommendationList.locator("li").first();
    await expect(firstCard.getByRole("button", { name: "Draft" })).toBeVisible();

    // reason strings are exact backend contract text (engine/draft_sim.py's
    // _reasons()): every recommendation carries at least one of these two as
    // its first reason, and DraftSessionPanel's "may not last" filtering only
    // ever strips a later reason, never the first -- so this always holds
    await expect(firstCard.locator("ul li").first()).toHaveText(
      /Fills your .+ need|Best player available/,
    );

    await firstCard.getByRole("button", { name: "Draft" }).click();
    await expect(sessionSection.getByText("Your picks (1)")).toBeVisible();

    // the recommendation panel refreshes for the next pick and still carries
    // a reason -- proves the recommend round trip works past the first pick.
    // Team 1 (the default slot) doesn't pick again until overall 16, so by
    // now the opponent-log list has entries too -- re-scope through the
    // named recommendation list rather than "first li in the section"
    const nextCard = recommendationList.locator("li").first();
    await expect(nextCard.getByRole("button", { name: "Draft" })).toBeVisible();
    await expect(nextCard.locator("ul li").first()).toHaveText(
      /Fills your .+ need|Best player available/,
    );
  });
});
