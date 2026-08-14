import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { ModelExplanations } from "@/lib/api";
import {
  EXPLANATIONS_REASON_TOKENS,
  describeExplanationsReason,
  modelRankByPlayerKey,
  reasoningByPlayerKey,
} from "./tokens";

function backendSource(relative: string): string {
  return readFileSync(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), `../../../../backend/${relative}`),
    "utf-8",
  );
}

describe("describeExplanationsReason", () => {
  it("covers every reason token the backend can emit", () => {
    // pinned against the backend's own vocabulary: a REASON_* constant added
    // there without a translation here fails this test instead of printing a
    // raw contract key on the page
    const source = backendSource("src/ninecat/advisor/types.py");
    const backendTokens = [...source.matchAll(/^REASON_[A-Z_]+ = "([a-z_]+)"$/gm)].map(
      (m) => m[1],
    );

    expect(backendTokens.length).toBeGreaterThan(0);
    expect([...backendTokens].sort()).toEqual([...EXPLANATIONS_REASON_TOKENS].sort());
  });

  it("says the ranking is still the engine's on every failure", () => {
    for (const token of EXPLANATIONS_REASON_TOKENS) {
      const text = describeExplanationsReason(token);
      if (text === null) continue;
      // the point of every one of these notes: explanations are missing, the
      // recommendations are not
      expect(text).toContain("engine");
      expect(text).not.toContain("Unrecognized");
    }
  });

  it("says nothing when there is no reason", () => {
    expect(describeExplanationsReason(null)).toBeNull();
  });

  it("says nothing when there was nothing to explain", () => {
    // the empty-list state already covers this; a second note would be noise
    expect(describeExplanationsReason("empty_shortlist")).toBeNull();
  });

  it("marks an unknown token as a gap instead of humanizing it", () => {
    const text = describeExplanationsReason("some_new_failure");
    expect(text).toContain("unrecognized");
    expect(text).toContain("some_new_failure");
  });
});

const EXPLANATIONS: ModelExplanations = {
  model: "claude-opus-5",
  summary: "Take the big.",
  ranked: [
    { player_key: "2", reasoning: "Fills the rebounding gap." },
    { player_key: "1", reasoning: "Still the safer floor." },
  ],
};

describe("reasoningByPlayerKey", () => {
  it("keys reasoning by player rather than by position", () => {
    // the model reordered: pairing by index would put "Fills the rebounding
    // gap" on player 1, who the engine had first
    const byKey = reasoningByPlayerKey(EXPLANATIONS);

    expect(byKey.get("2")).toBe("Fills the rebounding gap.");
    expect(byKey.get("1")).toBe("Still the safer floor.");
  });

  it("is empty when there are no explanations", () => {
    expect(reasoningByPlayerKey(null).size).toBe(0);
  });
});

describe("modelRankByPlayerKey", () => {
  it("reports the model's 1-based order", () => {
    const ranks = modelRankByPlayerKey(EXPLANATIONS);

    expect(ranks.get("2")).toBe(1);
    expect(ranks.get("1")).toBe(2);
  });

  it("is empty when there are no explanations", () => {
    expect(modelRankByPlayerKey(null).size).toBe(0);
  });
});
