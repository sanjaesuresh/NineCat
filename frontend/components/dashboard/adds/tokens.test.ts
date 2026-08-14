import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CONTRACT_KEY_BY_LABEL, categoryLabelOrGap } from "@/components/dashboard/categoryKeys";
import {
  OPPONENT_REASON_TOKENS,
  STATIC_REASON_TOKENS,
  describeOpponentReason,
  describeReason,
} from "./tokens";

const CONTRACT_KEYS = Object.values(CONTRACT_KEY_BY_LABEL);

function backendSource(relative: string): string {
  return readFileSync(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), `../../../../backend/${relative}`),
    "utf-8",
  );
}

describe("categoryLabelOrGap", () => {
  it("labels every known contract key", () => {
    for (const key of CONTRACT_KEYS) {
      expect(categoryLabelOrGap(key)).not.toContain("Unrecognized");
    }
  });

  it("marks an unknown key as a gap instead of printing it as a category", () => {
    // the old `?? key` spelling rendered a bare contract key in the same chip
    // as a real category label -- indistinguishable from "REB" on screen
    const text = categoryLabelOrGap("some_new_cat");
    expect(text).toContain("Unrecognized");
    expect(text).toContain("some_new_cat");
  });
});

describe("describeReason", () => {
  it("translates every category token", () => {
    for (const key of CONTRACT_KEYS) {
      const text = describeReason(`category:${key}`);
      expect(text).not.toContain(key);
      expect(text).not.toContain("unrecognized");
    }
  });

  it("keeps the key when the category is unknown", () => {
    expect(describeReason("category:brand_new")).toContain("brand_new");
  });

  it("translates both fixed tokens and flags anything else", () => {
    for (const token of STATIC_REASON_TOKENS) {
      expect(describeReason(token)).not.toContain("Unrecognized");
    }
    expect(describeReason("something_new")).toContain("Unrecognized reason");
  });
});

describe("describeOpponentReason", () => {
  it("translates all four values and flags a fifth", () => {
    for (const token of OPPONENT_REASON_TOKENS) {
      expect(describeOpponentReason(token)).not.toContain("Unrecognized");
    }
    expect(describeOpponentReason("brand_new_reason")).toContain("Unrecognized status");
  });
});

describe("cross-language contract", () => {
  // the Adds token vocabulary spans two backend modules; without this pin a
  // reworded token falls through to the "Unrecognized" fallback silently.
  // Same pattern as trades/tokens.test.ts and draftSession.test.ts.
  it("still matches the literals waivers.py and routes.py emit", () => {
    const waivers = backendSource("src/ninecat/engine/waivers.py");
    for (const token of STATIC_REASON_TOKENS) expect(waivers).toContain(`"${token}"`);

    const routes = backendSource("src/ninecat/api/routes.py");
    for (const token of OPPONENT_REASON_TOKENS) expect(routes).toContain(`"${token}"`);
  });
});
