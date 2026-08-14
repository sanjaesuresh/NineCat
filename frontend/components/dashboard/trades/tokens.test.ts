import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CONTRACT_KEY_BY_LABEL } from "@/components/dashboard/categoryKeys";
import {
  STATIC_REASON_TOKENS,
  VERDICT_TOKENS,
  describeReason,
  isVerdictToken,
} from "./tokens";

const CONTRACT_KEYS = Object.values(CONTRACT_KEY_BY_LABEL);

function backendSource(module: string): string {
  return readFileSync(
    path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      `../../../../backend/src/ninecat/engine/${module}`,
    ),
    "utf-8",
  );
}

describe("describeReason", () => {
  it("translates every category token in all three families without leaking the raw key", () => {
    for (const key of CONTRACT_KEYS) {
      for (const prefix of ["gained:", "lost:", "collapsed:"]) {
        const text = describeReason(`${prefix}${key}`);
        expect(text).not.toContain(key);
        expect(text).not.toContain("Unrecognized");
      }
    }
  });

  it("does not phrase a collapse the same way as an ordinary loss", () => {
    // a collapse means the category stops being a strength at all -- if these
    // two read identically the page understates the only downside that forces
    // trade_eval.py to reject a trade outright
    expect(describeReason("collapsed:reb")).not.toBe(describeReason("lost:reb"));
  });

  it("translates every fixed token", () => {
    for (const token of STATIC_REASON_TOKENS) {
      expect(describeReason(token)).not.toContain("Unrecognized");
    }
  });

  it("surfaces an unknown token as a visible gap rather than fluent prose", () => {
    expect(describeReason("brand_new_token")).toContain("Unrecognized reason");
    // a known prefix carrying an unknown category is still a gap
    expect(describeReason("gained:not_a_category")).toContain("Unrecognized category");
  });
});

describe("verdict tokens", () => {
  it("recognizes exactly the four backend values", () => {
    for (const token of VERDICT_TOKENS) expect(isVerdictToken(token)).toBe(true);
    expect(isVerdictToken("favours_me")).toBe(false);
  });
});

describe("cross-language contract", () => {
  // reads engine/trade_eval.py directly rather than trusting the two files to
  // stay in sync by convention: a reworded token on the backend would otherwise
  // fall through to the "Unrecognized" fallback silently on a page nobody
  // re-reads. Same pin as draftSession.test.ts's MAY_NOT_LAST_REASON.
  it("still matches the reason and verdict literals trade_eval.py emits", () => {
    const src = backendSource("trade_eval.py");
    for (const token of STATIC_REASON_TOKENS) expect(src).toContain(`"${token}"`);
    for (const token of VERDICT_TOKENS) expect(src).toContain(`"${token}"`);
    for (const prefix of ["gained:", "lost:", "collapsed:"]) {
      expect(src).toContain(`f"${prefix}`);
    }
  });
});
