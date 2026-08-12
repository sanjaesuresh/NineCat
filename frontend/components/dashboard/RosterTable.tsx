import type { RosterPlayer } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import PlayerAvatar from "./PlayerAvatar";
import InjuryBadge from "./InjuryBadge";
import { formatStatValue } from "./format";
import { CONTRACT_KEY_BY_LABEL } from "./categoryKeys";

/**
 * The signature box-score treatment applied to a roster: one row per player,
 * the same 9 category columns used everywhere else in the product. Scrolls
 * within its own container on narrow screens — never the page itself.
 */
export default function RosterTable({ roster }: { roster: RosterPlayer[] }) {
  if (roster.length === 0) {
    return (
      <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
        No players on this roster yet.
      </p>
    );
  }

  // relative: makes this the positioning context for absolutely-positioned
  // sr-only children so they stay clipped inside the scroll container
  // instead of escaping to the initial containing block and stretching the page
  return (
    <div className="relative overflow-x-auto border border-rule">
      <table className="w-full min-w-[640px] border-collapse text-left">
        <caption className="sr-only">Your roster, with 9-category averages</caption>
        <thead>
          <tr className="border-b-2 border-ink">
            <th scope="col" className="px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70">
              Player
            </th>
            <th scope="col" className="px-2 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70">
              Pos
            </th>
            <th scope="col" className="px-2 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70">
              Status
            </th>
            {CATEGORIES.map((cat) => (
              <th
                key={cat}
                scope="col"
                className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                {cat}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {roster.map((player) => (
            <tr key={player.yahoo_player_key} className="border-b border-rule last:border-b-0">
              <td className="px-3 py-2">
                <div className="flex items-center gap-3">
                  <PlayerAvatar src={player.headshot_url} />
                  <span className="font-body text-ink">{player.name}</span>
                </div>
              </td>
              <td className="px-2 py-2 font-mono text-xs text-ink/80">{player.position}</td>
              <td className="px-2 py-2">
                <InjuryBadge status={player.injury_status} />
              </td>
              {CATEGORIES.map((cat) => (
                <td
                  key={cat}
                  className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-sm text-ink"
                >
                  {/* averages is keyed by contract key (e.g. "fg_pct"), not the display label */}
                  {formatStatValue(cat, player.averages?.[CONTRACT_KEY_BY_LABEL[cat]])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
