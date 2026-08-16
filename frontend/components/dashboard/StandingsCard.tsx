import type { StandingsEntry } from "@/lib/api";
import { emptyStateClasses, tableRowClasses } from "./layout/layoutTokens";
import { columnHeaderClasses, eyebrowClasses, numericClasses } from "@/components/dashboard/layout/typography";

export default function StandingsCard({
  standings,
  myTeamId,
}: {
  standings: StandingsEntry[];
  // overview.my_team_id — null when the caller has no linked team in this league
  myTeamId: number | null;
}) {
  if (standings.length === 0) {
    return (
      <p className={emptyStateClasses()}>
        Standings aren&apos;t available yet.
      </p>
    );
  }

  // relative: keeps absolutely-positioned sr-only children clipped inside this
  // scroll container instead of escaping to the initial containing block
  // tabIndex + named region: keyboard scroll access once the table overflows
  // (WCAG 2.1.1) -- see RosterTable for the full reasoning
  const caption = "League standings";
  return (
    <div
      className="relative overflow-x-auto border border-rule"
      tabIndex={0}
      role="region"
      aria-label={caption}
    >
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">{caption}</caption>
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
              Team
            </th>
            <th
              scope="col"
              className={`px-3 py-2 text-right ${columnHeaderClasses()}`}
            >
              W
            </th>
            <th
              scope="col"
              className={`px-3 py-2 text-right ${columnHeaderClasses()}`}
            >
              L
            </th>
            <th
              scope="col"
              className={`px-3 py-2 text-right ${columnHeaderClasses()}`}
            >
              T
            </th>
          </tr>
        </thead>
        <tbody>
          {standings.map((team, i) => {
            const isMine = myTeamId !== null && team.team_id === myTeamId;
            return (
              <tr
                key={team.team_id}
                className={tableRowClasses(i, { rowCount: standings.length })}
              >
                <td className={`px-3 py-2 text-right ${numericClasses()}`}>{team.rank}</td>
                {/* my-team emphasis is the dot + "Your team" label plus name
                    weight -- a stripe or row fill was the side-stripe
                    anti-pattern, and no bg pairing here clears contrast */}
                <td className={`px-2 py-1 text-ink ${isMine ? "font-semibold" : ""}`}>
                  {team.name}
                  {isMine && (
                    <span className={`ml-2 inline-flex items-center gap-1.5 ${eyebrowClasses("ink")}`}>
                      <span className="h-1.5 w-1.5 rounded-full bg-court" aria-hidden="true" />
                      Your team
                    </span>
                  )}
                </td>
                <td className={`px-3 py-2 text-right ${numericClasses()}`}>{team.wins}</td>
                <td className={`px-3 py-2 text-right ${numericClasses()}`}>{team.losses}</td>
                <td className={`px-3 py-2 text-right ${numericClasses()}`}>{team.ties}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
