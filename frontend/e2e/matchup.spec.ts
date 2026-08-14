import { test, expect, type Page } from "@playwright/test";

// End-to-end coverage for the Matchup Monitor (docs/matchup-monitor-plan.md,
// sub-project 2, T9) -- dev-login only, no live Yahoo access, same
// stack/setup as draft.spec.ts/smoke.spec.ts (see README's "E2E smoke test"
// section). Follows draft.spec.ts's conventions: page.request for dev-login
// (shares the browser context's cookie jar with page.goto below), role-based
// locators keyed off accessible names/captions, and structural/ordering
// assertions rather than brittle exact numbers -- the seeded weekly
// projection depends on schedule and rate data that may be tuned later (see
// the plan's Risks section).
//
// Category labels/verdict vocabulary are re-declared here (not imported from
// app source) to match draft.spec.ts's own convention of small local
// constants -- if the frontend contract drifts, the assertions below fail
// loudly instead of silently importing the drift.
const CATEGORY_LABELS = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"];
// VerdictBadge's labels ("Winning"/"Losing"/"Close"/"Tied") render with a CSS
// `uppercase` class -- innerText reflects the CSS text-transform, not the DOM
// text, so this list matches what actually renders
const VERDICT_LABELS = ["WINNING", "LOSING", "CLOSE", "TIED"];

// contract keys/tokens that must never reach the rendered page in bare form
// (categoryKeys.ts/tokens.ts exist specifically to translate these) -- this
// bug class has shipped twice already (draft board's punt rationale, and a
// near-miss on this very page's "no_games_in_window" note) and been caught
// in design review both times, so it gets an automated guard here.
const FORBIDDEN_RAW_TOKENS = [
  "fg_pct",
  "ft_pct",
  "tov",
  "tpm",
  "no_games_in_window",
  "no_candidates",
  "invalid_window",
];

async function devLoginAndOpenMatchupTab(page: Page) {
  const devLogin = await page.request.post("/api/auth/dev-login");
  expect(devLogin.status()).toBe(204);

  await page.goto("/dashboard");
  // dashboard/page.tsx auto-redirects to /dashboard/{leagueId} once it sees
  // the dev user's single linked league (same as draft.spec.ts/smoke.spec.ts)
  await page.waitForURL(/\/dashboard\/\d+$/);

  // prove the Matchup tab is now a real link, not one of DashboardNav's
  // COMING_SOON badges -- those render as a plain <span aria-disabled="true">
  // with a "Soon" chip and are never a link, so getByRole("link") only finds
  // My Team/Draft/Matchup/Settings, never Adds/Trades
  const matchupLink = page.getByRole("link", { name: "Matchup", exact: true });
  await expect(matchupLink).toBeVisible();
  // Adds/Trades are still coming-soon -- distinguishes "Matchup is a real
  // link" from "DashboardNav stopped rendering Soon badges at all"
  await expect(page.getByText("Soon").first()).toBeVisible();

  await matchupLink.click();
  await page.waitForURL(/\/dashboard\/\d+\/matchup$/);
}

test.describe("matchup monitor", () => {
  test("dev-login reaches the matchup page via a real nav link", async ({ page }) => {
    await devLoginAndOpenMatchupTab(page);

    await expect(page.getByRole("heading", { name: "Matchup", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Matchup", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("scoreboard, category verdicts, focus categories, builds, and add schedule all render honestly", async ({
    page,
  }) => {
    await devLoginAndOpenMatchupTab(page);

    // --- projected scoreboard: both sides + a score line -------------------
    const scoreGroup = page.getByRole("group", { name: "Projected category score" });
    await expect(scoreGroup).toBeVisible();
    // the two big digit paragraphs, in document order (mine, then theirs) --
    // never asserted against exact values since the seeded projection can be
    // retuned, only that they're a valid category-count score line
    const scoreTexts = await scoreGroup.locator("p.font-display.text-5xl").allInnerTexts();
    expect(scoreTexts).toHaveLength(2);
    const [mineScore, theirScore] = scoreTexts.map((t) => Number(t.trim()));
    expect(Number.isInteger(mineScore)).toBe(true);
    expect(Number.isInteger(theirScore)).toBe(true);
    expect(mineScore).toBeGreaterThanOrEqual(0);
    expect(theirScore).toBeGreaterThanOrEqual(0);
    // 9 categories total; a tied category counts to neither side, so the two
    // win counts can never exceed the category count
    expect(mineScore + theirScore).toBeLessThanOrEqual(9);

    // --- nine category rows, both team names, verdicts from the 4-value set
    const board = page.getByRole("table", { name: /Projected category totals,/ });
    await expect(board).toBeVisible();
    await expect(board.getByRole("columnheader", { name: "Dev Team" })).toBeVisible();
    await expect(board.getByRole("columnheader", { name: "Rival Team" })).toBeVisible();

    const categoryLabels = (
      await board.locator("tbody tr td:first-child").allInnerTexts()
    ).map((t) => t.trim());
    // ordering property: the 9 rows follow the fixed CATEGORIES order, not a
    // re-sorted or partial list
    expect(categoryLabels).toEqual(CATEGORY_LABELS);

    const verdictTexts = (
      await board.locator("tbody tr td:nth-child(4)").allInnerTexts()
    ).map((t) => t.trim());
    expect(verdictTexts).toHaveLength(9);
    for (const verdict of verdictTexts) {
      // membership check doubles as a "the comparison actually resolved"
      // guard -- a missing verdict renders as a bare "—", which is not a
      // member of the 4-value set and would fail this loop
      expect(VERDICT_LABELS).toContain(verdict);
    }

    // --- focus categories section renders (populated or the honest empty state)
    const focusSection = page.locator("section:has(#focus-heading)");
    await expect(focusSection).toBeVisible();
    await expect(
      focusSection.getByText(
        /Ranked most flippable first\.|No categories are close enough to be worth targeting this week\./,
      ),
    ).toBeVisible();

    // --- both build profiles render (mine + opponent, 9 category cells each)
    const buildTables = page.getByRole("table", {
      name: "Category build — mean z-score per category",
    });
    await expect(buildTables).toHaveCount(2);
    for (let i = 0; i < 2; i++) {
      await expect(buildTables.nth(i).locator("tbody td")).toHaveCount(9);
    }

    // --- add-schedule table renders, and flags the past demo week honestly
    const addSection = page.locator("section:has(#streaming-heading)");
    await expect(addSection).toBeVisible();
    await expect(addSection.getByText(/Adds used \d+/)).toBeVisible();

    // the seeded demo week (2025-12-01..07) is in the past, so the backend
    // clamps as_of into the week and returns window_basis "full_week" -- the
    // page must say these aren't adds you can still make today, not imply
    // they're live recommendations
    await expect(
      addSection.getByRole("status").filter({ hasText: "not adds you can still make" }),
    ).toBeVisible();

    const addTable = addSection.getByRole("table", { name: "Recommended streaming adds by day" });
    if ((await addTable.count()) > 0) {
      await expect(addTable).toBeVisible();
    } else {
      // no candidate slots this week -- the empty state must still explain
      // why (a note, or the plain "no adds recommended" message), never a
      // silently blank section
      await expect(
        addSection
          .getByText("No streaming adds recommended this week.")
          .or(addSection.locator("ul li").first()),
      ).toBeVisible();
    }

    // --- no raw contract keys or bare note tokens anywhere on the rendered page
    const pageText = await page.locator("body").innerText();
    for (const token of FORBIDDEN_RAW_TOKENS) {
      expect(pageText).not.toContain(token);
    }
  });
});
