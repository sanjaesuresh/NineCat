import { afterEach, describe, expect, it, vi } from "vitest";
import { DataUnavailableError, loadPlayers } from "./data";

describe("loadPlayers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("surfaces DataUnavailableError on 404 (dataset not synced yet)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
    );

    await expect(loadPlayers()).rejects.toBeInstanceOf(DataUnavailableError);
  });

  it("surfaces DataUnavailableError when the response body is not valid JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not json", { status: 200 })),
    );

    await expect(loadPlayers()).rejects.toBeInstanceOf(DataUnavailableError);
  });

  it("returns the typed dataset on success", async () => {
    const dataset = { season: "2026-27", players: [] };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    await expect(loadPlayers()).resolves.toMatchObject({ season: "2026-27" });
  });
});
