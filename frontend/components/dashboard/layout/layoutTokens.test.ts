import { describe, expect, it } from "vitest";
import {
  controlMotionClasses,
  noticeClasses,
  noticeDotClasses,
  pageStackClasses,
  panelClasses,
  panelHeadingId,
  statRowClasses,
  statTileClasses,
  tableRowClasses,
} from "./layoutTokens";

describe("panelClasses", () => {
  it("includes a padding class by default", () => {
    expect(panelClasses().split(" ")).toContain("p-5");
  });

  it("omits the padding class when flush", () => {
    expect(panelClasses({ flush: true }).split(" ")).not.toContain("p-5");
  });

  it("always includes the hairline border and panel background", () => {
    expect(panelClasses()).toContain("border-rule");
    expect(panelClasses()).toContain("bg-panel");
    expect(panelClasses({ flush: true })).toContain("border-rule");
    expect(panelClasses({ flush: true })).toContain("bg-panel");
  });

  it("emits the hairline border class for the default tone, and no alert border class", () => {
    const classes = panelClasses({ tone: "default" }).split(" ");
    expect(classes).toContain("border-rule");
    expect(classes).not.toContain("border-alert");
  });

  it("emits the alert border class for the destructive tone, and no hairline class", () => {
    const classes = panelClasses({ tone: "destructive" }).split(" ");
    expect(classes).toContain("border-alert");
    expect(classes).not.toContain("border-rule");
  });

  it("defaults to the hairline border when no tone is passed", () => {
    const classes = panelClasses().split(" ");
    expect(classes).toContain("border-rule");
    expect(classes).not.toContain("border-alert");
  });
});

describe("controlMotionClasses", () => {
  it("pins the one recipe: colour transitions at 150ms on the shared easing token", () => {
    const classes = controlMotionClasses().split(" ");
    expect(classes).toContain("transition-colors");
    expect(classes).toContain("duration-150");
    // the landing's Hero ships the same easing -- dashboard and chrome must not drift
    expect(classes).toContain("ease-[var(--ease-out-quart)]");
  });

  it("emits exactly one duration and one easing", () => {
    const classes = controlMotionClasses().split(" ");
    expect(classes.filter((c) => c.startsWith("duration-"))).toHaveLength(1);
    expect(classes.filter((c) => c.startsWith("ease-"))).toHaveLength(1);
  });

  it("never animates transform -- a translate press is the bouncy-UI tell this system avoids", () => {
    expect(controlMotionClasses()).not.toMatch(/transition-(all|transform)|translate|scale-/);
  });

  it("carries a press state, so touch (where hover never fires) still gets acknowledged", () => {
    const classes = controlMotionClasses().split(" ");
    expect(classes).toContain("active:brightness-75");
    // exactly one active signal, and it is a colour step, never a movement
    expect(classes.filter((c) => c.startsWith("active:"))).toHaveLength(1);
  });
});

describe("noticeClasses", () => {
  it("draws a full hairline border, never a side stripe", () => {
    const classes = noticeClasses().split(" ");
    expect(classes).toContain("border");
    expect(classes).toContain("border-rule");
    // the border-l-4 stripe is the anti-pattern this helper retired
    expect(noticeClasses()).not.toMatch(/border-l-/);
  });

  it("carries no tone colour on the container -- severity lives in the dot", () => {
    expect(noticeClasses()).not.toMatch(/border-(alert|amber|court)/);
  });

  it("uses the named wash surface, not an ad-hoc opacity value", () => {
    const classes = noticeClasses().split(" ");
    expect(classes).toContain("bg-wash");
    expect(noticeClasses()).not.toMatch(/bg-ink\//);
  });

  it("bakes in its padding, like panelClasses", () => {
    expect(noticeClasses()).toMatch(/\bpx-\d/);
    expect(noticeClasses()).toMatch(/\bpy-\d/);
  });
});

describe("noticeDotClasses", () => {
  it("emits exactly one tone fill per call, matching the requested tone", () => {
    expect(noticeDotClasses("info").split(" ")).toContain("bg-court");
    expect(noticeDotClasses("warn").split(" ")).toContain("bg-amber");
    expect(noticeDotClasses("error").split(" ")).toContain("bg-alert");
    for (const tone of ["info", "warn", "error"] as const) {
      const fills = noticeDotClasses(tone)
        .split(" ")
        .filter((c) => c.startsWith("bg-"));
      expect(fills, tone).toHaveLength(1);
    }
  });

  it("is the shared dot shape -- round, 6px, non-shrinking", () => {
    for (const tone of ["info", "warn", "error"] as const) {
      const classes = noticeDotClasses(tone).split(" ");
      expect(classes, tone).toContain("rounded-full");
      expect(classes, tone).toContain("h-1.5");
      expect(classes, tone).toContain("w-1.5");
      expect(classes, tone).toContain("shrink-0");
    }
  });
});

describe("panelHeadingId", () => {
  it("slugifies a normal multi-word title", () => {
    expect(panelHeadingId("Focus Categories")).toBe("panel-focus-categories");
  });

  it("strips punctuation from a title", () => {
    expect(panelHeadingId("Punt Build: Overview")).toBe("panel-punt-build-overview");
  });

  it("collides two titles that differ only by punctuation -- acceptable since headingId can override", () => {
    // documents the known collision rather than hiding it: both slugify to
    // the same id, so a caller with two such titles on one page must pass
    // Panel's `headingId` prop to disambiguate
    expect(panelHeadingId("Punt Build")).toBe(panelHeadingId("Punt, Build"));
  });
});

describe("statRowClasses", () => {
  it("includes the full base class string at every count", () => {
    // pins every base-width class (grid, two-column, gap) so a regression
    // dropping one of them -- e.g. the two-column base -- fails here even
    // though the large-breakpoint tests below only check the appended class
    expect(statRowClasses(2)).toBe("grid grid-cols-2 gap-3");
  });

  it("stays two columns for a count of two", () => {
    expect(statRowClasses(2)).not.toContain("lg:grid-cols-4");
  });

  it("goes four columns at the large breakpoint for a count of exactly three", () => {
    // pins the >= 3 boundary itself -- a > 3 off-by-one would fail this
    expect(statRowClasses(3)).toContain("lg:grid-cols-4");
  });

  it("goes four columns at the large breakpoint for a count of four", () => {
    expect(statRowClasses(4)).toContain("lg:grid-cols-4");
  });
});

describe("pageStackClasses", () => {
  it("keeps the shared horizontal inset and panel rhythm", () => {
    const classes = pageStackClasses().split(" ");
    expect(classes).toContain("space-y-4");
    expect(classes).toContain("px-6");
    expect(classes).toContain("sm:px-10");
  });

  it("sits one rung tighter under the header than panels sit to each other", () => {
    // mt-3 (12px) against space-y-4 (16px) is the deliberate rhythm variation;
    // a regression back to mt-4 restores the flagged uniform spacing
    expect(pageStackClasses().split(" ")).toContain("mt-3");
    expect(pageStackClasses()).not.toContain("mt-4");
  });
});

describe("statTileClasses", () => {
  it("always includes the hairline border", () => {
    expect(statTileClasses().split(" ")).toContain("border-rule");
  });

  it("always includes the standard 20px padding", () => {
    expect(statTileClasses().split(" ")).toContain("p-5");
  });
});

describe("tableRowClasses", () => {
  const ROW_COUNT = 4;

  it("always includes the fixed row-height class, including first and last", () => {
    expect(tableRowClasses(0, { rowCount: ROW_COUNT }).split(" ")).toContain("h-11");
    expect(tableRowClasses(1, { rowCount: ROW_COUNT }).split(" ")).toContain("h-11");
    expect(tableRowClasses(2, { rowCount: ROW_COUNT }).split(" ")).toContain("h-11");
    expect(
      tableRowClasses(ROW_COUNT - 1, { rowCount: ROW_COUNT }).split(" "),
    ).toContain("h-11");
  });

  it("has the separator class on a middle row", () => {
    expect(tableRowClasses(1, { rowCount: ROW_COUNT }).split(" ")).toContain(
      "border-rule",
    );
  });

  it("has no separator class on the last row", () => {
    expect(
      tableRowClasses(ROW_COUNT - 1, { rowCount: ROW_COUNT }).split(" "),
    ).not.toContain("border-rule");
  });

  it("has the separator class on the first row of a multi-row table -- not a special case", () => {
    expect(tableRowClasses(0, { rowCount: ROW_COUNT }).split(" ")).toContain(
      "border-rule",
    );
  });

  it("has no separator on a single-row table's only row, since it is also the last", () => {
    expect(tableRowClasses(0, { rowCount: 1 }).split(" ")).not.toContain(
      "border-rule",
    );
  });

  it("never returns a background class, for any row", () => {
    for (let i = 0; i < ROW_COUNT; i++) {
      const classes = tableRowClasses(i, { rowCount: ROW_COUNT }).split(" ");
      expect(classes.some((c) => c.startsWith("bg-"))).toBe(false);
    }
  });
});
