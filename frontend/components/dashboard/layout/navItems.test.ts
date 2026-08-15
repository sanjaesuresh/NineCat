import { describe, expect, it } from "vitest";
import { buildNavItems, isActiveNavItem } from "./navItems";

describe("buildNavItems", () => {
  it("returns six entries with the exact labels in order", () => {
    const items = buildNavItems("8252");
    expect(items.map((item) => item.label)).toEqual([
      "My Team",
      "Draft",
      "Matchup",
      "Adds",
      "Trades",
      "Settings",
    ]);
  });

  it("builds hrefs off the league root for My Team and root + segment for the rest", () => {
    const items = buildNavItems("8252");
    const byLabel = Object.fromEntries(items.map((item) => [item.label, item.href]));
    expect(byLabel["My Team"]).toBe("/dashboard/8252");
    expect(byLabel["Draft"]).toBe("/dashboard/8252/draft");
  });

  it("pins all six hrefs, not just My Team and Draft", () => {
    const items = buildNavItems("8252");
    expect(items.map((item) => item.href)).toEqual([
      "/dashboard/8252",
      "/dashboard/8252/draft",
      "/dashboard/8252/matchup",
      "/dashboard/8252/adds",
      "/dashboard/8252/trades",
      "/dashboard/8252/settings",
    ]);
  });

  it("uses the passed-in league id rather than a hardcoded value", () => {
    const items = buildNavItems("99999");
    expect(items.map((item) => item.href)).toEqual([
      "/dashboard/99999",
      "/dashboard/99999/draft",
      "/dashboard/99999/matchup",
      "/dashboard/99999/adds",
      "/dashboard/99999/trades",
      "/dashboard/99999/settings",
    ]);
  });

  it("assigns distinct, stable keys for every entry", () => {
    const items = buildNavItems("8252");
    const keys = items.map((item) => item.key);
    expect(keys).toEqual(["team", "draft", "matchup", "adds", "trades", "settings"]);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("isActiveNavItem", () => {
  it("returns true when the pathname exactly equals the entry href", () => {
    const items = buildNavItems("8252");
    const draft = items.find((item) => item.label === "Draft")!;
    expect(isActiveNavItem(draft, "/dashboard/8252/draft")).toBe(true);
  });

  it("returns false for My Team when the pathname is a child route, so only one link is ever current", () => {
    const items = buildNavItems("8252");
    const myTeam = items.find((item) => item.label === "My Team")!;
    expect(isActiveNavItem(myTeam, "/dashboard/8252/draft")).toBe(false);
  });

  it("marks exactly one item active for each of the six item pathnames", () => {
    const items = buildNavItems("8252");
    for (const pathname of items.map((item) => item.href)) {
      const activeCount = items.filter((item) => isActiveNavItem(item, pathname)).length;
      expect(activeCount).toBe(1);
    }
  });
});
