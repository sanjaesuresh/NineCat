import { describe, expect, it } from "vitest";
import type { DraftBoardPlayer, DraftLivePick, DraftLiveResponse } from "@/lib/api";
import { chooseDraftMode, deriveLivePicks, shouldPollLiveDraft, unmappedPickLabel } from "./liveDraftSession";

function board(overrides: Partial<DraftBoardPlayer> = {}): DraftBoardPlayer {
  return {
    player_key: "101",
    name: "Nikola Jokic",
    position: "C",
    nba_person_id: 900101,
    headshot_url: null,
    best_class: "elite",
    projected_games: 70,
    base: 10,
    vorp: 5,
    value: 20,
    replacement: 5,
    zscores: {},
    stat_basis: "projection",
    ...overrides,
  };
}

function livePick(overrides: Partial<DraftLivePick> = {}): DraftLivePick {
  return {
    pick: 1,
    round: 1,
    team_key: "1.t.1",
    is_mine: false,
    player_key: "101",
    yahoo_player_key: "1.p.101",
    ...overrides,
  };
}

function liveResponse(overrides: Partial<DraftLiveResponse> = {}): DraftLiveResponse {
  return {
    draft_status: "draft",
    draft_type: "snake",
    num_teams: 8,
    my_team_key: "1.t.2",
    my_slot: 2,
    overall_pick: 2,
    picks: [],
    unmapped: [],
    stale: false,
    synced_at: "2026-09-12T00:00:00Z",
    ...overrides,
  };
}

describe("chooseDraftMode", () => {
  it("is mock when the probe failed (null)", () => {
    expect(chooseDraftMode(null)).toBe("mock");
  });

  it("is mock for predraft", () => {
    expect(chooseDraftMode(liveResponse({ draft_status: "predraft" }))).toBe("mock");
  });

  it("is live for an active draft", () => {
    expect(chooseDraftMode(liveResponse({ draft_status: "draft" }))).toBe("live");
  });

  it("is live for postdraft with recorded picks", () => {
    expect(
      chooseDraftMode(liveResponse({ draft_status: "postdraft", picks: [livePick()] })),
    ).toBe("live");
  });

  it("is mock for postdraft with no picks (draft never actually ran)", () => {
    expect(chooseDraftMode(liveResponse({ draft_status: "postdraft", picks: [] }))).toBe("mock");
  });
});

describe("shouldPollLiveDraft", () => {
  it("polls only while status is draft and the tab is visible", () => {
    expect(shouldPollLiveDraft("draft", true)).toBe(true);
    expect(shouldPollLiveDraft("draft", false)).toBe(false);
    expect(shouldPollLiveDraft("predraft", true)).toBe(false);
    expect(shouldPollLiveDraft("postdraft", true)).toBe(false);
    expect(shouldPollLiveDraft(null, true)).toBe(false);
  });
});

describe("deriveLivePicks", () => {
  it("splits picks by is_mine and resolves names/positions off the board", () => {
    const players = [board({ player_key: "101", name: "Nikola Jokic", position: "C" })];
    const picks = [
      livePick({ pick: 1, is_mine: false, player_key: "101" }),
      livePick({ pick: 2, is_mine: true, player_key: "202", yahoo_player_key: "1.p.202" }),
    ];
    // second pick isn't on the board -- exercise the off-board branch too
    const result = deriveLivePicks(picks, players);

    expect(result.oppPicks).toEqual([{ playerKey: "101", name: "Nikola Jokic", position: "C" }]);
    expect(result.myPicks).toEqual([
      { playerKey: "202", name: unmappedPickLabel(picks[1]), position: null },
    ]);
    expect(result.takenKeys).toEqual(new Set(["101", "202"]));
  });

  it("renders an honest placeholder for a pick with no player_key at all", () => {
    const pick = livePick({ pick: 5, is_mine: false, player_key: null, yahoo_player_key: "1.p.999" });
    const result = deriveLivePicks([pick], []);

    expect(result.oppPicks).toHaveLength(1);
    expect(result.oppPicks[0].name).toBe("Unmapped pick #5");
    // synthetic key, never a fabricated player id
    expect(result.oppPicks[0].playerKey).not.toBe("1.p.999");
    expect(result.takenKeys.has(result.oppPicks[0].playerKey)).toBe(true);
  });

  it("lastOpponentRun is every opponent pick after the user's most recent pick", () => {
    const players = [board({ player_key: "101" }), board({ player_key: "202", name: "B" })];
    const picks = [
      livePick({ pick: 1, is_mine: false, player_key: "101" }),
      livePick({ pick: 2, is_mine: true, player_key: "202" }),
      livePick({ pick: 3, is_mine: false, player_key: null, yahoo_player_key: "x" }),
      livePick({ pick: 4, is_mine: false, player_key: null, yahoo_player_key: "y" }),
    ];
    const result = deriveLivePicks(picks, players);

    expect(result.lastOpponentRun).toHaveLength(2);
    expect(result.lastOpponentRun.map((p) => p.name)).toEqual([
      "Unmapped pick #3",
      "Unmapped pick #4",
    ]);
  });

  it("lastOpponentRun is every opponent pick so far when the user hasn't picked yet", () => {
    const picks = [livePick({ pick: 1, is_mine: false }), livePick({ pick: 2, is_mine: false, player_key: "202" })];
    const result = deriveLivePicks(picks, [board()]);

    expect(result.lastOpponentRun).toHaveLength(2);
  });

  it("returns empty structures for no picks yet", () => {
    const result = deriveLivePicks([], []);
    expect(result).toEqual({ myPicks: [], oppPicks: [], lastOpponentRun: [], takenKeys: new Set() });
  });
});
