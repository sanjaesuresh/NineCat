import { test, expect, type Page } from "@playwright/test";

// End-to-end coverage for the Trade Analyzer page (docs/trade-analyzer-plan.md
// task 7, docs/trades-page-plan.md) -- dev-login only, no live Yahoo access,
// same stack/setup as matchup.spec.ts (see the README's "E2E smoke test"
// section). Structural assertions, not exact numbers: the seeded rosters can
// be retuned, and every number here derives from them.
//
// The non-emptiness assertion below is load-bearing. Before the seed was
// rebalanced, the dev roster's nine categories all labelled "average", so it
// had no surplus and no deficit, candidate generation returned nothing, and
// this page rendered its empty state forever. A backend test pins the same
// fact (test_trades_over_the_real_dev_seed_proposes_guards_for_bigs); this one
// pins that the page actually puts it on screen.

// TradeVerdictBadge's labels render through a CSS `uppercase` class, so
// innerText differs from the DOM string -- matched here as rendered.
const VERDICT_LABELS = ["FAVORS YOU", "FAVORS THEM", "BALANCED", "NOT WORTH IT"];

// contract keys and tokens that must never reach the screen in bare form.
// trades/tokens.ts exists to translate these; this guard exists because the
// bug class has shipped twice in this project.
const FORBIDDEN_RAW_TOKENS = [
  "fg_pct",
  "ft_pct",
  "tov",
  "tpm",
  "no_downside",
  "category_impact_only",
  "favors_me",
  "favors_them",
];

async function devLoginAndOpenTradesTab(page: Page) {
  const devLogin = await page.request.post("/api/auth/dev-login");
  expect(devLogin.status()).toBe(204);

  await page.goto("/dashboard");
  await page.waitForURL(/\/dashboard\/\d+$/);

  const tradesLink = page.getByRole("link", { name: "Trades", exact: true });
  await expect(tradesLink).toBeVisible();
  // Trades was the last coming-soon badge -- nothing in the nav should still
  // be gated
  await expect(page.getByText("Soon")).toHaveCount(0);

  await tradesLink.click();
  await page.waitForURL(/\/dashboard\/\d+\/trades$/);
}

test.describe("trade analyzer", () => {
  test("dev-login reaches the trades page via a real nav link", async ({ page }) => {
    await devLoginAndOpenTradesTab(page);

    await expect(page.getByRole("heading", { name: "Trades", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Trades", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("proposals, both sides' strengths, and the modelling disclosure all render", async ({
    page,
  }) => {
    await devLoginAndOpenTradesTab(page);

    // --- trade partner picker, over the league's other teams ---------------
    const partner = page.getByLabel("Trade partner");
    await expect(partner).toBeVisible();
    // the seeded league has exactly one other team, so the picker must still
    // render sensibly with a single option rather than looking broken
    await expect(partner.locator("option")).not.toHaveCount(0);
    await expect(page.getByRole("heading", { name: /Proposed trades with / })).toBeVisible();

    // --- the modelling disclosure, which is the reason several backend
    // decisions exist and must never be quietly dropped ---------------------
    await expect(page.getByText(/not positional scarcity/)).toBeVisible();
    await expect(page.getByText(/combinations? examined/)).toBeVisible();
    await expect(page.getByText(/whether the other manager would accept/)).toBeVisible();

    // --- at least one real proposal ----------------------------------------
    const proposals = page.getByRole("article");
    await expect(proposals.first()).toBeVisible();
    const proposalCount = await proposals.count();
    expect(proposalCount).toBeGreaterThan(0);

    const first = proposals.first();
    // give and get are both non-empty: a proposal with one side blank would
    // still "render", and would be meaningless
    await expect(first.getByRole("heading", { name: "You give" })).toBeVisible();
    await expect(first.getByRole("heading", { name: "You get" })).toBeVisible();

    // every verdict badge is one of the four known values -- a missing or
    // unrecognized verdict renders as "Unrecognized verdict (...)" and fails
    // this membership check rather than passing silently
    for (let i = 0; i < proposalCount; i++) {
      const badge = proposals.nth(i).locator("span.uppercase").first();
      const text = (await badge.innerText()).trim();
      expect(VERDICT_LABELS).toContain(text);
    }

    // --- before/after profiles are behind a disclosure and really expand ----
    const disclosure = first.getByText("Before and after, both rosters");
    await expect(disclosure).toBeVisible();
    // collapsed by default: four nine-column profiles per card is a wall
    await expect(
      first.getByRole("table", { name: "Category build — mean z-score per category" }),
    ).toHaveCount(0);
    await disclosure.click();
    await expect(
      first.getByRole("table", { name: "Category build — mean z-score per category" }),
    ).toHaveCount(4);

    // --- both sides' strength tables, nine rows each ------------------------
    const strengthTables = page.getByRole("table", {
      name: "Category strengths, depth and fragility for this roster",
    });
    await expect(strengthTables).toHaveCount(2);
    for (let i = 0; i < 2; i++) {
      await expect(strengthTables.nth(i).locator("tbody tr")).toHaveCount(9);
    }

    // --- no raw contract keys or bare tokens anywhere on the rendered page --
    const pageText = await page.locator("body").innerText();
    for (const token of FORBIDDEN_RAW_TOKENS) {
      expect(pageText).not.toContain(token);
    }
  });
});
