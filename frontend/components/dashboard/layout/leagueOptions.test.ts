import { describe, expect, it } from "vitest";
import { buildLeagueOptions } from "./leagueOptions";
import type { League } from "@/lib/api";

const league = (id: number, name: string): League => ({
  id,
  yahoo_league_key: `key-${id}`,
  name,
  season: "2025-26",
  synced_at: null,
});

describe("buildLeagueOptions", () => {
  it("shows a single loading option while the fetch is still in flight", () => {
    const options = buildLeagueOptions({
      leagueId: "42",
      leagueName: null,
      leagues: [],
      leaguesLoaded: false,
    });
    expect(options).toEqual([{ id: "42", name: "Loading…" }]);
  });

  it("shows a terminal, non-loading label once settled with zero leagues", () => {
    const options = buildLeagueOptions({
      leagueId: "42",
      leagueName: null,
      leagues: [],
      leaguesLoaded: true,
    });
    expect(options).toEqual([{ id: "42", name: "League unavailable" }]);
    expect(options[0].name).not.toBe("Loading…");
  });

  it("lists every league by string id when the routed id matches one of them", () => {
    const options = buildLeagueOptions({
      leagueId: "42",
      leagueName: "My League",
      leagues: [league(42, "My League"), league(7, "Other League")],
      leaguesLoaded: true,
    });
    expect(options).toEqual([
      { id: "42", name: "My League" },
      { id: "7", name: "Other League" },
    ]);
  });

  it("prepends a disabled placeholder when the routed id matches no fetched league", () => {
    const options = buildLeagueOptions({
      leagueId: "999",
      leagueName: null,
      leagues: [league(42, "My League"), league(7, "Other League")],
      leaguesLoaded: true,
    });
    expect(options).toEqual([
      { id: "999", name: "Unknown league", disabled: true },
      { id: "42", name: "My League" },
      { id: "7", name: "Other League" },
    ]);
  });

  it("uses the best-effort leagueName for the placeholder when one is known", () => {
    const options = buildLeagueOptions({
      leagueId: "999",
      leagueName: "Stale Bookmark League",
      leagues: [league(42, "My League")],
      leaguesLoaded: true,
    });
    expect(options[0]).toEqual({ id: "999", name: "Stale Bookmark League", disabled: true });
  });
});
