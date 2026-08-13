import type { DraftBoardPlayer } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { CONTRACT_KEY_BY_LABEL } from "@/components/dashboard/categoryKeys";
import { formatGamesCount, formatSignedNumber } from "@/components/dashboard/format";
import PlayerAvatar from "@/components/dashboard/PlayerAvatar";

/**
 * Ranked draftable-player board. Follows RosterTable's table conventions
 * exactly (overflow wrapper + relative, min-w, border-b-2 header, font-mono
 * stats, sr-only caption) so the draft page reads as the same box-score
 * motif as the rest of the dashboard, just with a valuation column instead
 * of raw per-game stats. Games is the LAST column deliberately, so adding it
 * never shifts the Value column's position (rank/name/pos/value stay 1-4).
 */
export default function BigBoardTable({
  players,
  source,
  takenKeys,
  onDraft,
  puntPending,
}: {
  players: DraftBoardPlayer[];
  source: string | null;
  takenKeys: Set<string>;
  onDraft: (player: DraftBoardPlayer) => void;
  puntPending: boolean;
}) {
  if (players.length === 0) {
    return (
      <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
        No draftable players yet — the season&apos;s projections and averages haven&apos;t
        synced for this league.
      </p>
    );
  }

  const hasFallback = players.some((p) => p.stat_basis === "season_average");

  return (
    <div>
      <div className="mb-3 space-y-1">
        <p className="font-mono text-xs uppercase tracking-wide text-ink/70">
          {source
            ? "Valued using synced player projections."
            : "No projections synced yet — every player is valued off season averages."}
        </p>
        <p className="text-xs text-ink/80">
          Value is worth over a replacement-level player at that slot, risk-adjusted for
          projected games — higher is better. The 9 category columns are z-scores against
          this pool (0 = average).
        </p>
        {hasFallback && (
          <p className="font-mono text-[0.65rem] uppercase tracking-wide text-ink/80">
            SZN AVG marks a player with no projection yet, valued off season average instead.
          </p>
        )}
      </div>

      {/* relative: makes this the positioning context for the sr-only caption
          so it stays clipped inside the scroll container instead of
          escaping to the initial containing block and stretching the page */}
      <div className="relative overflow-x-auto border border-rule" aria-busy={puntPending}>
        <table className="w-full min-w-[980px] border-collapse text-left">
          <caption className="sr-only">
            Draftable players ranked by value, with per-category z-scores
          </caption>
          <thead>
            <tr className="border-b-2 border-ink">
              <th
                scope="col"
                className="px-2 py-2 text-right font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Rank
              </th>
              <th
                scope="col"
                className="px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Player
              </th>
              <th
                scope="col"
                className="px-2 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Pos
              </th>
              <th
                scope="col"
                className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Value
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
              <th
                scope="col"
                className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70"
              >
                Games
              </th>
              <th scope="col" className="px-2 py-2">
                <span className="sr-only">Draft action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {players.map((player, i) => {
              const taken = takenKeys.has(player.player_key);
              return (
                <tr
                  key={player.player_key}
                  className={`border-b border-rule last:border-b-0 ${taken ? "bg-ink/[0.03]" : ""}`}
                >
                  <td className="px-2 py-2 text-right font-mono text-xs text-ink/80">{i + 1}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-3">
                      <PlayerAvatar src={player.headshot_url} />
                      <span className="flex items-center gap-1.5">
                        <span className={`font-body text-ink ${taken ? "line-through decoration-ink/40" : ""}`}>
                          {player.name}
                        </span>
                        {player.stat_basis === "season_average" && (
                          <span className="border border-rule px-1 py-0.5 font-mono text-[0.6rem] uppercase tracking-wide text-ink/80">
                            SZN AVG
                          </span>
                        )}
                      </span>
                    </div>
                  </td>
                  <td className="px-2 py-2 font-mono text-xs text-ink/80">{player.position ?? "—"}</td>
                  <td className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-sm text-ink">
                    {formatSignedNumber(player.value)}
                  </td>
                  {CATEGORIES.map((cat) => (
                    <td
                      key={cat}
                      className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-sm text-ink"
                    >
                      {formatSignedNumber(player.zscores?.[CONTRACT_KEY_BY_LABEL[cat]])}
                    </td>
                  ))}
                  <td className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-sm text-ink">
                    {formatGamesCount(player.projected_games)}
                  </td>
                  <td className="px-2 py-2 text-right">
                    {taken ? (
                      <span className="font-mono text-[0.65rem] uppercase tracking-wide text-ink/70">
                        Drafted
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onDraft(player)}
                        className="min-h-[1.75rem] shrink-0 border border-ink px-2 py-1 font-mono text-[0.65rem] uppercase tracking-wide text-ink transition-colors hover:bg-ink hover:text-paper"
                      >
                        Draft
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
