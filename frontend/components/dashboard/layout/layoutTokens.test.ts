import { describe, expect, it } from "vitest";
import {
  panelClasses,
  panelHeadingId,
  statRowClasses,
  statTileClasses,
  tableRowClasses,
} from "./layoutTokens";

describe("panelClasses", () => {
  it("includes a padding class by default", () => {
    expect(panelClasses().split(" ")).toContain("p-4");
  });

  it("omits the padding class when flush", () => {
    expect(panelClasses({ flush: true }).split(" ")).not.toContain("p-4");
  });

  it("always includes the hairline border and panel background", () => {
    expect(panelClasses()).toContain("border-rule");
    expect(panelClasses()).toContain("bg-panel");
    expect(panelClasses({ flush: true })).toContain("border-rule");
    expect(panelClasses({ flush: true })).toContain("bg-panel");
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

describe("statTileClasses", () => {
  it("always includes the hairline border", () => {
    expect(statTileClasses().split(" ")).toContain("border-rule");
  });

  it("always includes the standard 16px padding", () => {
    expect(statTileClasses().split(" ")).toContain("p-4");
  });
});

describe("tableRowClasses", () => {
  const ROW_COUNT = 4;

  it("always includes the fixed row-height class, including first and last", () => {
    expect(tableRowClasses(0, { rowCount: ROW_COUNT }).split(" ")).toContain("h-9");
    expect(tableRowClasses(1, { rowCount: ROW_COUNT }).split(" ")).toContain("h-9");
    expect(tableRowClasses(2, { rowCount: ROW_COUNT }).split(" ")).toContain("h-9");
    expect(
      tableRowClasses(ROW_COUNT - 1, { rowCount: ROW_COUNT }).split(" "),
    ).toContain("h-9");
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
