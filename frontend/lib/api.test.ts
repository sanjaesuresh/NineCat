import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  getDraftBoard,
  getLeagueAdds,
  getLeagueMatchup,
  getLeagueTrades,
  getMe,
  isUnauthorized,
  postDraftRecommend,
  refreshLeague,
} from "./api";

// helper to build a minimal fetch Response mock
function mockResponse(options: {
  ok: boolean;
  status: number;
  json?: unknown;
  jsonThrows?: boolean;
}): Response {
  return {
    ok: options.ok,
    status: options.status,
    json: options.jsonThrows
      ? () => Promise.reject(new SyntaxError("Unexpected token"))
      : () => Promise.resolve(options.json),
  } as unknown as Response;
}

describe("api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getMe hits /api/me and returns parsed JSON", async () => {
    const payload = { display_name: "Sanjae", leagues: [] };
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: payload })
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getMe();

    expect(result).toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/me",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("throws ApiError with status 401 on unauthorized response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ ok: false, status: 401, json: { detail: "Not authenticated" } })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getMe()).rejects.toMatchObject({ status: 401 });

    try {
      await getMe();
      throw new Error("expected getMe to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(isUnauthorized(err)).toBe(true);
    }
  });

  it("resolves void for a 204 response (refreshLeague)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ ok: true, status: 204 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await refreshLeague(42);

    expect(result).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/42/refresh",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("throws ApiError status 500 without crashing on non-JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ ok: false, status: 500, jsonThrows: true })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getMe()).rejects.toMatchObject({ status: 500 });
    await expect(getMe()).rejects.toBeInstanceOf(ApiError);
    expect(isUnauthorized(new ApiError("x", 500))).toBe(false);
  });

  it("resolves void on a 200 with a text body (refreshLeague)", async () => {
    // void endpoints must never call .json() on success, so a body that would
    // throw on parse (e.g. plain text) must not surface at all
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ ok: true, status: 200, jsonThrows: true })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(refreshLeague(42)).resolves.toBeUndefined();
  });

  it("throws ApiError (not SyntaxError) on a 200 with invalid JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ ok: true, status: 200, jsonThrows: true })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getMe()).rejects.toBeInstanceOf(ApiError);
    await expect(getMe()).rejects.not.toBeInstanceOf(SyntaxError);
    await expect(getMe()).rejects.toMatchObject({ status: 200 });
  });

  it("getDraftBoard hits the board endpoint with no query string when opts omitted", async () => {
    const payload = { players: [], punt_suggestions: [], source: null, stale: false, synced_at: "x" };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getDraftBoard(7);

    expect(result).toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/draft/board",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("getDraftBoard encodes source and repeated punt query params", async () => {
    const payload = { players: [], punt_suggestions: [], source: "hashtag", stale: false, synced_at: "x" };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    await getDraftBoard(7, { source: "hashtag", punt: ["ft_pct", "tov"] });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/draft/board?source=hashtag&punt=ft_pct&punt=tov",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("getDraftBoard encodes repeated my_player_key query params", async () => {
    const payload = { players: [], punt_suggestions: [], source: null, stale: false, synced_at: "x" };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    await getDraftBoard(7, { myPlayerKeys: ["101", "202"] });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/draft/board?my_player_key=101&my_player_key=202",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("postDraftRecommend posts the body as JSON and returns parsed JSON", async () => {
    const payload = { recommendations: [], stale: false, synced_at: "x" };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    const body = { my_player_keys: ["1"], taken_player_keys: ["2"], overall_pick: 3, limit: 5 };
    const result = await postDraftRecommend(7, body);

    expect(result).toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/draft/recommend",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    );
  });

  it("postDraftRecommend surfaces a 400 as ApiError with the body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ ok: false, status: 400, json: { detail: "overall_pick must be >= 1" } })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      postDraftRecommend(7, { my_player_keys: [], taken_player_keys: [], overall_pick: 0 })
    ).rejects.toMatchObject({ status: 400 });
  });

  it("getLeagueMatchup hits the matchup endpoint with no query string when opts omitted", async () => {
    const payload = {
      week: 5,
      week_range: { start_date: "2025-11-17", end_date: "2025-11-23", is_derived: false },
      as_of: "2025-11-17",
      mine: {
        team_id: 1,
        team_key: "466.l.1.t.1",
        name: "My Team",
        projection: { totals: {}, components: {}, games: 6, player_games: {} },
        build_profile: { totals: {}, labels: {}, means: {} },
      },
      opponent: null,
      opponent_reason: "no_matchup_this_week",
      comparison: null,
      schedule_coverage: { mine_games: 6, opponent_games: null, ok: true },
      streaming: null,
      stale: false,
      synced_at: "x",
    };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getLeagueMatchup(7);

    expect(result).toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/matchup",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("getLeagueMatchup encodes week and as_of query params", async () => {
    const payload = {
      week: 5,
      week_range: { start_date: "2025-11-17", end_date: "2025-11-23", is_derived: false },
      as_of: "2025-11-18",
      mine: {
        team_id: 1,
        team_key: "466.l.1.t.1",
        name: "My Team",
        projection: { totals: {}, components: {}, games: 6, player_games: {} },
        build_profile: { totals: {}, labels: {}, means: {} },
      },
      opponent: null,
      opponent_reason: "no_matchup_this_week",
      comparison: null,
      schedule_coverage: { mine_games: 6, opponent_games: null, ok: true },
      streaming: null,
      stale: false,
      synced_at: "x",
    };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    await getLeagueMatchup(7, { week: 5, asOf: "2025-11-18" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/matchup?week=5&as_of=2025-11-18",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("getLeagueMatchup surfaces a 404 as ApiError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ ok: false, status: 404, json: { detail: "League not found" } })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getLeagueMatchup(999)).rejects.toMatchObject({ status: 404 });
  });

  it("getLeagueAdds hits the adds endpoint with no query string when opts omitted", async () => {
    const payload = {
      week: 5,
      week_range: { start_date: "2025-11-17", end_date: "2025-11-23", is_derived: false },
      as_of: "2025-11-17",
      window_basis: "remaining",
      close_categories: [],
      opponent_reason: "no_opponent_in_matchup",
      candidates: [],
      schedule_coverage: { mine_games: 6, opponent_games: null, ok: true },
      stale: false,
      synced_at: "x",
    };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getLeagueAdds(7);

    expect(result).toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/adds",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("getLeagueAdds encodes week, as_of, repeated punt, and limit query params", async () => {
    const payload = {
      week: 5,
      week_range: { start_date: "2025-11-17", end_date: "2025-11-23", is_derived: false },
      as_of: "2025-11-18",
      window_basis: "remaining",
      close_categories: ["blk"],
      opponent_reason: null,
      candidates: [],
      schedule_coverage: { mine_games: 6, opponent_games: 5, ok: true },
      stale: false,
      synced_at: "x",
    };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    await getLeagueAdds(7, { week: 5, asOf: "2025-11-18", punt: ["ft_pct", "tov"], limit: 10 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/adds?week=5&as_of=2025-11-18&punt=ft_pct&punt=tov&limit=10",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("getLeagueAdds surfaces a 404 as ApiError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ ok: false, status: 404, json: { detail: "League not found" } })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getLeagueAdds(999)).rejects.toMatchObject({ status: 404 });
  });

  it("getLeagueTrades hits the trades endpoint with only team_id when opts omitted", async () => {
    const payload = {
      mine: { team_id: 1, categories: {}, surplus: [], deficit: [] },
      theirs: { team_id: 2, categories: {}, surplus: [], deficit: [] },
      players: {},
      verdicts: [],
      evaluated: 0,
      truncated: false,
      value_basis: "category_impact_only",
      stale: false,
      synced_at: "x",
    };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getLeagueTrades(7, 2);

    expect(result).toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/trades?team_id=2",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("getLeagueTrades encodes max_package and limit query params", async () => {
    const payload = {
      mine: { team_id: 1, categories: {}, surplus: [], deficit: [] },
      theirs: { team_id: 2, categories: {}, surplus: [], deficit: [] },
      players: {},
      verdicts: [],
      evaluated: 0,
      truncated: false,
      value_basis: "category_impact_only",
      stale: false,
      synced_at: "x",
    };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ ok: true, status: 200, json: payload }));
    vi.stubGlobal("fetch", fetchMock);

    await getLeagueTrades(7, 2, { maxPackage: 1, limit: 5 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/leagues/7/trades?team_id=2&max_package=1&limit=5",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("getLeagueTrades surfaces a 400 as ApiError (same-team comparison)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 400,
        json: { detail: "team_id must be a different team than your own" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getLeagueTrades(7, 1)).rejects.toMatchObject({ status: 400 });
  });
});
