import { describe, expect, it } from "vitest";
import { defaultFilters, filterPlayers, normalizeSearchText } from "./filterPlayers";
import { fixturePlayers } from "./__fixtures__/players";

describe("filterPlayers", () => {
  it("filtering by position C hides guards-only players", () => {
    const result = filterPlayers(fixturePlayers, { ...defaultFilters, position: "C" });
    const names = result.map((p) => p.name);
    expect(names).toContain("Jokić Center");
    expect(names).toContain("Two-Way Big");
    expect(names).not.toContain("Ace Guard");
    expect(names).not.toContain("Rookie Wonder");
    expect(names).not.toContain("Bench Guard");
  });

  it("search normalizes diacritics so 'jokic' finds 'Jokić Center'", () => {
    const result = filterPlayers(fixturePlayers, { ...defaultFilters, search: "jokic" });
    expect(result.map((p) => p.name)).toEqual(["Jokić Center"]);
  });

  it("normalizeSearchText strips combining marks and lowercases", () => {
    expect(normalizeSearchText("Jokić")).toBe("jokic");
    expect(normalizeSearchText("SHAI")).toBe("shai");
  });

  it("injury risk filter (multi) narrows to the selected labels", () => {
    const result = filterPlayers(fixturePlayers, { ...defaultFilters, injuryRisk: ["high"] });
    expect(result.map((p) => p.name)).toEqual(["Forward Star"]);
  });

  it("consensus flag filter narrows to model_loves", () => {
    const result = filterPlayers(fixturePlayers, { ...defaultFilters, consensusFlag: "model_loves" });
    expect(result.map((p) => p.name)).toEqual(["Rookie Wonder"]);
  });

  it("rookie-only filter uses the player_id prefix", () => {
    const result = filterPlayers(fixturePlayers, { ...defaultFilters, rookieOnly: true });
    expect(result.map((p) => p.name)).toEqual(["Rookie Wonder"]);
  });

  it("age range tolerates null age (excludes it rather than crashing) when a bound is set", () => {
    const result = filterPlayers(fixturePlayers, { ...defaultFilters, minAge: 20 });
    expect(result.map((p) => p.name)).not.toContain("Rookie Wonder"); // null age
  });

  it("empty-result combo (impossible filter intersection) returns an empty array", () => {
    const result = filterPlayers(fixturePlayers, {
      ...defaultFilters,
      position: "C",
      rookieOnly: true,
    });
    expect(result).toEqual([]);
  });
});
