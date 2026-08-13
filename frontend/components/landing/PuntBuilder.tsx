"use client";

import {
  CATS,
  pickLabel,
  rosterStrength,
  snakeDraft,
  type Cat,
} from "@/lib/puntDraft";
import { togglePunt, usePunts } from "@/lib/puntStore";
import { SOURCE_NAME, SOURCE_SEASON, type PlayerRow } from "@/lib/hashtagPool";
import { formatCounting, formatPct } from "./format";

// a roster total at or beyond this magnitude reads as a real category lean rather
// than noise — mirrors the mockup's ticker/footnote classification thresholds exactly
const STRONG_THRESHOLD = 1.5;

// raw per-game accessor for the nine stat columns, keyed the same way puntDraft's
// internal statValue() is — kept local since it's pure display formatting, not draft math
function statValue(player: PlayerRow, cat: Cat): number {
  switch (cat) {
    case "pts":
      return player.points;
    case "reb":
      return player.rebounds;
    case "ast":
      return player.assists;
    case "stl":
      return player.steals;
    case "blk":
      return player.blocks;
    case "tpm":
      return player.threes;
    case "fgp":
      return player.fieldGoalPct;
    case "ftp":
      return player.freeThrowPct;
    case "to":
      return player.turnovers;
  }
}

// percentages print without a leading zero (".569", not "0.569") — matches the
// mockup's pct() helper exactly, since the build table is read like a stat sheet
function formatStat(cat: Cat, value: number): string {
  return cat === "fgp" || cat === "ftp" ? formatPct(value) : formatCounting(value);
}

export default function PuntBuilder() {
  // first real browser consumer of usePunts(); see puntStore.ts's wiring note —
  // verified manually since the test suite has no jsdom
  const punts = usePunts();
  const mine = snakeDraft(punts);
  const strength = rosterStrength(mine.map((pick) => pick.player));

  const puntLabels = punts.map(
    (cat) => CATS.find((c) => c.key === cat)?.label ?? cat,
  );
  const puntNames = puntLabels.join(" + ");
  // non-punted categories the build leans into — footnote falls back to "balance"
  // when nothing clears the strong threshold, matching the mockup's copy exactly
  const strongLabels = CATS.filter(
    (c) => !punts.includes(c.key) && strength[c.key] >= STRONG_THRESHOLD,
  ).map((c) => c.label);

  const footnote = `▲ strong · • average · ▼ conceded — punting ${puntNames || "none"} re-values every player before each pick; this board leans ${
    strongLabels.length ? strongLabels.join(", ") : "balance"
  }. Per-game projections: ${SOURCE_NAME}, ${SOURCE_SEASON}.`;

  const puntHint =
    punts.length === 2 ? `punting ${puntNames}` : "pick two categories to punt";

  // short summary read by assistive tech whenever a punt changes, instead of the
  // whole table re-announcing cell-by-cell (which useSyncExternalStore re-renders
  // wholesale on every toggle)
  const liveSummary = `Build updated: ${puntHint}. First pick ${mine[0].player.name} at ${pickLabel(
    mine[0].overall,
  )}.`;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-4 border-b-2 border-ink py-4">
        <span className="font-display text-[22px] tracking-[0.01em] text-ink">
          Your First Five — Pick Two Punts, Watch the Draft Change
        </span>
        <span className="font-condensed text-[12.5px] font-bold tracking-[0.08em] text-ink-muted uppercase">
          12-Team Snake · Slot 4 · {SOURCE_NAME} &apos;25&#8211;26 Per-Game
        </span>
      </div>

      <div
        role="group"
        aria-label="Choose two categories to punt"
        className="flex flex-wrap items-center gap-3 py-3.5"
      >
        <span className="font-condensed text-[12.5px] font-extrabold tracking-[0.1em] text-ink-muted uppercase">
          Punt two:
        </span>
        <span className="flex flex-wrap gap-2">
          {CATS.map((cat) => {
            const pressed = punts.includes(cat.key);
            return (
              <button
                key={cat.key}
                type="button"
                aria-pressed={pressed}
                onClick={() => togglePunt(cat.key)}
                className={`border-2 px-[13px] py-[7px] font-condensed text-[13px] font-extrabold tracking-[0.06em] uppercase transition-colors duration-150 ease-[var(--ease-out-quart)] ${
                  pressed
                    ? // border-transparent, not border-alert-fill: alert-fill is a
                      // fill-only token (not border-safe), and the border here was
                      // always meant to be invisible against the matching bg anyway
                      "border-transparent bg-alert-fill text-cream line-through"
                    : "border-ink/40 bg-transparent text-ink hover:border-ink"
                }`}
              >
                {cat.label}
              </button>
            );
          })}
        </span>
        <span className="font-condensed text-[12.5px] font-bold tracking-[0.06em] text-gold uppercase">
          {puntHint}
        </span>
      </div>

      <div aria-live="polite" className="sr-only">
        {liveSummary}
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-[920px] w-full border-collapse font-condensed">
          <caption className="sr-only">
            Your projected first five picks for this build, updated live as you toggle
            punt categories above.
          </caption>
          <thead>
            <tr>
              <th
                scope="col"
                className="border-b-2 border-ink bg-ink-fill px-2 py-2.5 text-center text-[11.5px] font-extrabold tracking-[0.07em] text-cream uppercase"
              >
                Pick
              </th>
              <th
                scope="col"
                className="border-b-2 border-ink bg-ink-fill px-0.5 py-2.5 text-left text-[11.5px] font-extrabold tracking-[0.07em] text-cream uppercase"
              >
                Player
              </th>
              {CATS.map((cat) => (
                <th
                  key={cat.key}
                  scope="col"
                  className="border-b-2 border-ink bg-ink-fill px-2 py-2.5 text-center text-[11.5px] font-extrabold tracking-[0.07em] text-cream uppercase"
                >
                  {cat.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {mine.map(({ player, overall }) => (
              <tr
                key={overall}
                className="border-b border-rule even:bg-paper-2"
              >
                <td className="w-px px-2 py-2.5 text-center align-middle whitespace-nowrap">
                  <span className="font-display text-[15px] text-red-ink">
                    {pickLabel(overall)}
                  </span>
                  <small className="block font-condensed text-[10.5px] font-semibold tracking-[0.05em] text-ink-muted">
                    #{overall} overall
                  </small>
                </td>
                <th
                  scope="row"
                  className="px-0.5 py-2.5 text-left align-middle font-normal whitespace-nowrap"
                >
                  <span className="font-condensed text-[15.5px] font-bold text-ink">
                    {player.name}
                  </span>
                  <small className="block font-condensed text-[11.5px] font-semibold tracking-[0.03em] text-ink-muted">
                    {player.position} · {player.team}
                  </small>
                </th>
                {CATS.map((cat) => (
                  <td
                    key={cat.key}
                    className="px-2 py-2.5 text-center align-middle font-mono text-[14.5px] font-semibold whitespace-nowrap text-ink"
                  >
                    {formatStat(cat.key, statValue(player, cat.key))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div
        role="note"
        aria-label="Composite nine-category read for this build"
        className="flex flex-wrap border-t-2 border-ink font-condensed text-[13px] font-bold tracking-[0.04em]"
      >
        {CATS.map((cat) => {
          const punted = punts.includes(cat.key);
          const total = strength[cat.key];
          const strong = !punted && total >= STRONG_THRESHOLD;
          const weak = punted || total <= -STRONG_THRESHOLD;
          // arrows/bullet carry the read on their own — color is a reinforcement,
          // never the only signal (punted rows also say "punted" in text)
          const glyph = punted ? "▼" : strong ? "▲" : weak ? "▼" : "•";
          // punted rows already spell out "punted" in text below; the other three
          // reads only exist as a glyph, so give those an sr-only word too (I2)
          const glyphLabel = punted ? null : strong ? "strong" : weak ? "weak" : "average";
          return (
            <span
              key={cat.key}
              className="border-r border-rule px-4 py-3 text-ink uppercase last:border-r-0"
            >
              <b
                aria-hidden="true"
                className={`mr-[5px] font-display font-normal ${
                  strong ? "text-blue-txt" : weak ? "text-red-ink" : ""
                }`}
              >
                {glyph}
              </b>
              {glyphLabel && <span className="sr-only">{glyphLabel} </span>}
              {cat.label}
              {punted ? " · punted" : ""}
            </span>
          );
        })}
      </div>

      <p className="border-t border-rule py-2.5 font-condensed text-[11.5px] font-semibold tracking-[0.04em] text-ink-muted">
        {footnote}
      </p>
    </div>
  );
}
