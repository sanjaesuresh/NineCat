import type { DraftBoardPlayer } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { CONTRACT_KEY_BY_LABEL } from "@/components/dashboard/categoryKeys";
import { formatGamesCount, formatSignedNumber } from "@/components/dashboard/format";
import { emptyStateClasses, tableRowClasses } from "@/components/dashboard/layout/layoutTokens";
import PlayerAvatar from "@/components/dashboard/PlayerAvatar";
import { captionClasses, columnHeaderClasses, controlClasses, eyebrowClasses, numericClasses, proseClasses, uiTextClasses } from "@/components/dashboard/layout/typography";

/**
 * Ranked draftable-player board. Follows RosterTable's table conventions
 * exactly (overflow wrapper + relative, min-w, border-b-2 header, font-mono
 * stats, sr-only caption) so the draft page reads as the same box-score
 * motif as the rest of the dashboard, just with a valuation column instead
 * of raw per-game stats. Games is the LAST column deliberately, so adding it
 * never shifts the Value column's position (rank/name/pos/value stay 1-4).
 *
 * Only ever rendered inside the draft page's "Big board" Panel, which is
 * `flush` (no inner padding) specifically so this table's 980px min-width
 * has the maximum room the page can give it (review fix, dash regrid task 9
 * pass 2 -- a 360px right rail plus the panel's own 32px of padding put the
 * table underwater at every viewport width). Because the panel supplies no
 * padding, this component owns its own horizontal inset for the descriptive
 * text above the table, while the table's scroll container runs edge to
 * edge and borrows the panel's own left/right border instead of drawing its
 * own (hence border-y, not border, below).
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
    // m-4 (not the surrounding p-4/px-4 convention): the panel this renders
    // in is flush and supplies zero inner padding, so this empty state needs
    // its own inset on every side, not just left/right
    return (
      <p className={`m-4 ${emptyStateClasses()}`}>
        No draftable players yet — the season&apos;s projections and averages haven&apos;t
        synced for this league.
      </p>
    );
  }

  const hasFallback = players.some((p) => p.stat_basis === "season_average");

  return (
    <div>
      <div className="mb-3 space-y-1 px-4 pt-4">
        <p className={proseClasses("muted")}>
          {source
            ? "Valued using synced player projections."
            : "No projections synced yet — every player is valued off season averages."}
        </p>
        <p className={captionClasses()}>
          Value is worth over a replacement-level player at that slot, risk-adjusted for
          projected games — higher is better. The 9 category columns are z-scores against
          this pool (0 = average).
        </p>
        {hasFallback && (
          <p className={proseClasses("muted")}>
            SZN AVG marks a player with no projection yet, valued off season average instead.
          </p>
        )}
      </div>

      {/* relative: makes this the positioning context for the sr-only caption
          so it stays clipped inside the scroll container instead of
          escaping to the initial containing block and stretching the page.
          border-y (not border): the panel's own left/right border already
          runs flush against this container, so a left/right border here
          would just double it.
          tabIndex + named region: keyboard scroll access once the table
          overflows (WCAG 2.1.1) -- see RosterTable for the full reasoning */}
      <div
        className="relative overflow-x-auto border-y border-rule"
        aria-busy={puntPending}
        tabIndex={0}
        role="region"
        aria-label="Draftable players ranked by value, with per-category z-scores"
      >
        <table className="w-full min-w-[980px] border-collapse text-left">
          <caption className="sr-only">
            Draftable players ranked by value, with per-category z-scores
          </caption>
          <thead>
            <tr className="border-b-2 border-ink">
              <th
                scope="col"
                className={`px-3 py-2 text-right ${columnHeaderClasses()}`}
              >
                Rank
              </th>
              <th
                scope="col"
                className={`px-3 py-2 ${columnHeaderClasses()}`}
              >
                Player
              </th>
              <th
                scope="col"
                className={`px-3 py-2 ${columnHeaderClasses()}`}
              >
                Pos
              </th>
              <th
                scope="col"
                className={`whitespace-nowrap border-l border-rule px-3 py-2 text-right ${columnHeaderClasses()}`}
              >
                Value
              </th>
              {CATEGORIES.map((cat) => (
                <th
                  key={cat}
                  scope="col"
                  className={`whitespace-nowrap border-l border-rule px-3 py-2 text-right ${columnHeaderClasses()}`}
                >
                  {cat}
                </th>
              ))}
              <th
                scope="col"
                className={`whitespace-nowrap border-l border-rule px-3 py-2 text-right ${columnHeaderClasses()}`}
              >
                Games
              </th>
              <th scope="col" className="px-3 py-2">
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
                  className={
                    taken
                      ? `${tableRowClasses(i, { rowCount: players.length })} bg-wash`
                      : tableRowClasses(i, { rowCount: players.length })
                  }
                >
                  <td className={`px-3 py-2 text-right ${numericClasses("muted")}`}>{i + 1}</td>
                  <td className="px-3 py-1">
                    <div className="flex items-center gap-3">
                      <PlayerAvatar src={player.headshot_url} size="sm" />
                      <span className="flex items-center gap-1.5">
                        {/* whitespace-nowrap: without it a long name text-wraps inside
                            the flex item, blowing the row well past 36px -- every other
                            data cell here already carries this class */}
                        <span
                          className={`whitespace-nowrap font-body text-ink ${taken ? "line-through decoration-ink/40" : ""}`}
                        >
                          {player.name}
                        </span>
                        {player.stat_basis === "season_average" && (
                          <span className={`border border-rule px-1.5 py-0.5 ${eyebrowClasses()}`}>
                            SZN AVG
                          </span>
                        )}
                      </span>
                    </div>
                  </td>
                  {/* whitespace-nowrap: a dual-position value like "PG-SG" otherwise
                      breaks after the hyphen in a narrow column, wrapping to 2 lines
                      and blowing the row past 36px */}
                  <td className={`whitespace-nowrap px-3 py-2 ${uiTextClasses("muted")}`}>
                    {player.position ?? "—"}
                  </td>
                  <td className={`whitespace-nowrap border-l border-rule px-3 py-2 text-right ${numericClasses()}`}>
                    {formatSignedNumber(player.value)}
                  </td>
                  {CATEGORIES.map((cat) => (
                    <td
                      key={cat}
                      className={`whitespace-nowrap border-l border-rule px-3 py-2 text-right ${numericClasses()}`}
                    >
                      {formatSignedNumber(player.zscores?.[CONTRACT_KEY_BY_LABEL[cat]])}
                    </td>
                  ))}
                  <td className={`whitespace-nowrap border-l border-rule px-3 py-2 text-right ${numericClasses()}`}>
                    {formatGamesCount(player.projected_games)}
                  </td>
                  <td className="px-2 py-1 text-right">
                    {taken ? (
                      <span className={eyebrowClasses()}>
                        Drafted
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onDraft(player)}
                        className={`min-h-[2rem] shrink-0 border border-ink px-2.5 py-1 hover:bg-ink hover:text-paper ${controlClasses()}`}
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
