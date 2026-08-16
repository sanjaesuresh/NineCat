import { describe, expect, it } from "vitest";
import {
  captionClasses,
  columnHeaderClasses,
  controlClasses,
  eyebrowClasses,
  headingClasses,
  numericClasses,
  proseClasses,
  subheadingClasses,
  uiTextClasses,
} from "./typography";

// every helper at its default tone, so the policy tests below sweep the whole
// module in one pass. A helper added to typography.ts but not listed here
// escapes all of them -- keep this in sync when adding one.
const ALL: Record<string, string> = {
  headingClasses: headingClasses(),
  subheadingClasses: subheadingClasses(),
  eyebrowClasses: eyebrowClasses(),
  columnHeaderClasses: columnHeaderClasses(),
  numericClasses: numericClasses(),
  uiTextClasses: uiTextClasses(),
  proseClasses: proseClasses(),
  captionClasses: captionClasses(),
  controlClasses: controlClasses(),
};

// the named scale from globals.css. text-5xl is absent on purpose: the
// scoreboard hero number is pinned to that stock class by an immutable e2e
// locator (see globals.css), and no helper here should ever emit it.
// the named scale from globals.css. Tailwind's stock sizes (text-xs, text-sm,
// text-base, ...) are deliberately absent: they carry an implicit per-size
// line height, and relying on that is what left the dashboard with 7 explicit
// leading declarations in total.
const SCALE = [
  "text-headline",
  "text-figure",
  "text-section",
  "text-prose",
  "text-ui",
  "text-data",
  "text-caption",
  "text-eyebrow",
];

describe("type-role policy, across every helper", () => {
  it("emits exactly one size class, and it comes from the named scale", () => {
    for (const [name, classes] of Object.entries(ALL)) {
      const sizes = classes.split(" ").filter((c) => SCALE.includes(c));
      expect(sizes, name).toHaveLength(1);
    }
  });

  it("never emits a stock Tailwind size, which would bring an implicit leading", () => {
    for (const [name, classes] of Object.entries(ALL)) {
      expect(classes, name).not.toMatch(/\btext-(xs|sm|base|lg|xl|\dxl)\b/);
    }
  });

  it("never emits an arbitrary size value", () => {
    // the 66 text-[11px] / text-[0.65rem] / text-[0.6rem] declarations this
    // scale replaced are the reason this test exists
    for (const [name, classes] of Object.entries(ALL)) {
      expect(classes, name).not.toMatch(/\btext-\[/);
    }
  });

  it("emits exactly one text colour, and only from the two named tokens", () => {
    for (const [name, classes] of Object.entries(ALL)) {
      const colours = classes
        .split(" ")
        .filter((c) => c === "text-ink" || c === "text-ink-muted");
      expect(colours, name).toHaveLength(1);
    }
  });

  it("never emits an opacity-modified ink", () => {
    for (const [name, classes] of Object.entries(ALL)) {
      expect(classes, name).not.toMatch(/text-ink\/\d/);
    }
  });

  it("never emits padding -- that boundary belongs to the call site", () => {
    for (const [name, classes] of Object.entries(ALL)) {
      expect(classes, name).not.toMatch(/\b[pm][xytrbl]?-\d/);
    }
  });

  it("never emits standalone letter spacing -- tracking is bundled into text-eyebrow", () => {
    for (const [name, classes] of Object.entries(ALL)) {
      expect(classes, name).not.toMatch(/\btracking-/);
    }
  });

  it("never emits a standalone leading -- every scale step ships its own", () => {
    for (const [name, classes] of Object.entries(ALL)) {
      expect(classes, name).not.toMatch(/\bleading-/);
    }
  });
});

describe("family budget", () => {
  it("gives monospace to numeric text and nothing else", () => {
    const mono = Object.entries(ALL)
      .filter(([, classes]) => classes.split(" ").includes("font-mono"))
      .map(([name]) => name);
    expect(mono).toEqual(["numericClasses"]);
  });

  it("uses condensed for labels and controls, body for anything read as words", () => {
    expect(headingClasses()).toContain("font-condensed");
    expect(eyebrowClasses()).toContain("font-condensed");
    expect(subheadingClasses()).toContain("font-condensed");
    expect(columnHeaderClasses()).toContain("font-condensed");
    expect(controlClasses()).toContain("font-condensed");

    expect(uiTextClasses()).toContain("font-body");
    expect(proseClasses()).toContain("font-body");
    expect(captionClasses()).toContain("font-body");
  });

  it("gives every helper exactly one family", () => {
    for (const [name, classes] of Object.entries(ALL)) {
      const families = classes
        .split(" ")
        .filter((c) => /^font-(display|condensed|body|mono)$/.test(c));
      expect(families, name).toHaveLength(1);
    }
  });
});

describe("uppercase budget", () => {
  it("belongs to the eyebrow role and nothing else", () => {
    const shouting = Object.entries(ALL)
      .filter(([, classes]) => classes.split(" ").includes("uppercase"))
      .map(([name]) => name);
    expect(shouting).toEqual(["eyebrowClasses"]);
  });

  it("stays uppercase at both tones", () => {
    expect(eyebrowClasses("ink")).toContain("uppercase");
    expect(eyebrowClasses("muted")).toContain("uppercase");
  });
});

describe("tone parameter", () => {
  it("switches between the two tokens for every helper that takes one", () => {
    const helpers = [
      headingClasses,
      subheadingClasses,
      eyebrowClasses,
      numericClasses,
      uiTextClasses,
      proseClasses,
      captionClasses,
      controlClasses,
    ];
    for (const helper of helpers) {
      expect(helper("ink").split(" ")).toContain("text-ink");
      expect(helper("ink").split(" ")).not.toContain("text-ink-muted");
      expect(helper("muted").split(" ")).toContain("text-ink-muted");
      expect(helper("muted").split(" ")).not.toContain("text-ink");
    }
  });

  it("defaults headings, numbers and UI text to full-contrast ink", () => {
    expect(headingClasses().split(" ")).toContain("text-ink");
    expect(numericClasses().split(" ")).toContain("text-ink");
    expect(uiTextClasses().split(" ")).toContain("text-ink");
    expect(proseClasses().split(" ")).toContain("text-ink");
  });

  it("defaults eyebrows and captions to muted, since both are secondary by role", () => {
    expect(eyebrowClasses().split(" ")).toContain("text-ink-muted");
    expect(captionClasses().split(" ")).toContain("text-ink-muted");
  });
});

describe("motion budget", () => {
  it("bakes the shared motion recipe into controls, so no call site can forget it", () => {
    for (const tone of ["ink", "muted"] as const) {
      const classes = controlClasses(tone).split(" ");
      expect(classes).toContain("transition-colors");
      expect(classes).toContain("duration-150");
      expect(classes).toContain("ease-[var(--ease-out-quart)]");
      expect(classes).toContain("active:brightness-75");
    }
  });

  it("gives motion to controls and nothing else -- static text does not animate", () => {
    const moving = Object.entries(ALL)
      .filter(([, classes]) => /\btransition-/.test(classes))
      .map(([name]) => name);
    expect(moving).toEqual(["controlClasses"]);
  });
});

describe("role-specific requirements", () => {
  it("pins tabular figures onto numeric text -- monospace alone does not guarantee lining digits", () => {
    expect(numericClasses().split(" ")).toContain("tabular-nums");
    expect(numericClasses("muted").split(" ")).toContain("tabular-nums");
  });

  it("caps prose at a reading measure", () => {
    expect(proseClasses().split(" ")).toContain("max-w-[68ch]");
  });

  it("caps the measure at both tones", () => {
    expect(proseClasses("muted").split(" ")).toContain("max-w-[68ch]");
  });

  it("keeps a subheading a step below a panel title, so the two do not compete", () => {
    expect(headingClasses().split(" ")).toContain("text-section");
    expect(subheadingClasses().split(" ")).toContain("text-prose");
    expect(subheadingClasses()).toMatch(/\bfont-semibold\b/);
  });

  it("sets column-header weight explicitly, so no font-normal override is needed", () => {
    expect(columnHeaderClasses()).toMatch(/\bfont-semibold\b/);
  });

  it("states weight on every condensed helper, since no scale step declares one", () => {
    // the scale deliberately omits font-weight: Anton ships a single 400 cut,
    // so a step that set 600 would faux-bold the display face
    for (const classes of [headingClasses(), subheadingClasses(), eyebrowClasses(),
                           columnHeaderClasses(), controlClasses()]) {
      expect(classes).toMatch(/\bfont-semibold\b/);
    }
  });

  it("keeps column headers muted and non-shouting", () => {
    const classes = columnHeaderClasses().split(" ");
    expect(classes).toContain("text-ink-muted");
    expect(classes).not.toContain("uppercase");
  });

  it("does not cap the measure on anything but prose", () => {
    for (const [name, classes] of Object.entries(ALL)) {
      if (name === "proseClasses") continue;
      expect(classes, name).not.toMatch(/max-w-/);
    }
  });
});
