import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, getMe, isUnauthorized, refreshLeague } from "./api";

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
});
