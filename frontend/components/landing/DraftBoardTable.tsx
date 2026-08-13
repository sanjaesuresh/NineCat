"use client";

// reads usePunts (useSyncExternalStore), which only works client-side — split out
// of DraftBoard.tsx (design review finding I4) so the punt store only pulls this
// table + note line into the client bundle, not the whole section shell.
import { POOL, type PlayerRow } from "@/lib/hashtagPool";
import { CATS, pickLabel, snakeDraft, zScore, type Cat } from "@/lib/puntDraft";
import { usePunts } from "@/lib/puntStore";

const TOP_N = 8;

/**
 * Mockup rule that isn't in the shared engine: a player's "Elite In" categories are
 * their top three z-scores, turnovers excluded, sorted descending, joined with " · ".
 */
function eliteCategories(player: PlayerRow): string {
  return CATS.filter((c) => c.key !== "to")
    .map((c) => ({ label: c.label, z: zScore(player, c.key) }))
    .sort((a, b) => b.z - a.z)
    .slice(0, 3)
    .map((c) => c.label)
    .join(" · ");
}

function puntNames(punts: readonly Cat[]): string {
  return punts.map((key) => CATS.find((c) => c.key === key)?.label ?? key).join(" + ");
}

const headerCellClass =
  "bg-ink-fill px-2.5 py-2.5 text-left font-condensed text-[11.5px] font-extrabold uppercase tracking-[0.06em] text-cream";
const headerCellClassCenter = `${headerCellClass} text-center`;
const numCellClass = "px-2.5 py-2.5 text-center font-mono text-sm text-ink";

export default function DraftBoardTable() {
  const punts = usePunts();
  const picks = snakeDraft(punts);
  const firstPick = picks[0].player;

  // copy before sort: POOL is readonly, and Array.sort mutates in place
  const top8 = [...POOL].sort((a, b) => a.rank - b.rank).slice(0, TOP_N);
  const firstPickInTop8 = top8.some((p) => p.name === firstPick.name);
  const firstPickLabel = pickLabel(picks[0].overall);

  // both note variants are reused verbatim (up to the interpolated names) from the
  // approved mockup's render() — see d-retrodata.html board-note logic. The
  // in-top-8 branch keeps "at pick X"; the fallback branch drops "pick" to match
  // the mockup exactly (design review minor finding)
  const note = firstPickInTop8
    ? `▸ Gold row: your ${puntNames(punts)} punt build takes ${firstPick.name} at pick ${firstPickLabel}.`
    : `▸ Your ${puntNames(punts)} punt build passes this whole board and takes ${firstPick.name} (HTB #${firstPick.rank}) at ${firstPickLabel} — value the consensus ranks can't see.`;

  return (
    <>
      {/* overflow wrapper keeps the 760px-wide table from ever forcing the page
          body itself to scroll horizontally on narrow viewports */}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse font-condensed">
          <caption className="sr-only">
            Hashtag Basketball&apos;s top {TOP_N} players by rank. The row your current
            punt build would draft first is highlighted.
          </caption>
          <thead>
            <tr>
              <th scope="col" className={headerCellClass}>
                Rk
              </th>
              <th scope="col" className={headerCellClass}>
                Player
              </th>
              <th scope="col" className={headerCellClassCenter}>
                Pts
              </th>
              <th scope="col" className={headerCellClassCenter}>
                Reb
              </th>
              <th scope="col" className={headerCellClassCenter}>
                Ast
              </th>
              <th scope="col" className={headerCellClassCenter}>
                Blk
              </th>
              <th scope="col" className={headerCellClass}>
                Elite In
              </th>
            </tr>
          </thead>
          <tbody>
            {top8.map((p, i) => {
              const isRec = p.name === firstPick.name;
              return (
                <tr
                  key={p.name}
                  className={`border-b border-rule ${
                    isRec ? "bg-gold/16" : i % 2 === 1 ? "bg-paper-2" : ""
                  }`}
                >
                  <td
                    className={`px-2.5 py-2.5 font-display text-base ${isRec ? "text-gold" : "text-red-ink"}`}
                  >
                    {p.rank}
                  </td>
                  <th
                    scope="row"
                    className="px-2.5 py-2.5 text-left text-[15.5px] font-bold text-ink"
                  >
                    {p.name}
                    {/* colour alone can't carry the recommendation — name it for
                        screen readers too, not just via the gold row tint */}
                    {isRec && (
                      <span className="sr-only"> — your punt build&apos;s pick 1</span>
                    )}
                    <small className="block font-condensed text-[11px] font-semibold text-ink-muted">
                      {p.position} · {p.team}
                    </small>
                  </th>
                  <td className={numCellClass}>{p.points.toFixed(1)}</td>
                  <td className={numCellClass}>{p.rebounds.toFixed(1)}</td>
                  <td className={numCellClass}>{p.assists.toFixed(1)}</td>
                  <td className={numCellClass}>{p.blocks.toFixed(1)}</td>
                  <td className="px-2.5 py-2.5 text-[12.5px] font-bold tracking-[0.02em] text-blue-txt">
                    {eliteCategories(p)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="border-t-2 border-ink px-4 py-2.5 font-condensed text-[13px] font-bold uppercase tracking-[0.04em] text-gold">
        {note}
      </p>
    </>
  );
}
