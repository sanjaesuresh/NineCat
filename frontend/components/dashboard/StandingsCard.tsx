import type { StandingsEntry } from "@/lib/api";
import { tableRowClasses } from "./layout/layoutTokens";

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
      <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
        Standings aren&apos;t available yet.
      </p>
    );
  }

  // relative: keeps absolutely-positioned sr-only children clipped inside this
  // scroll container instead of escaping to the initial containing block
  return (
    <div className="relative overflow-x-auto border border-rule">
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">League standings</caption>
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
              className="px-2 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
            >
              Team
            </th>
            <th
              scope="col"
              className="px-2 py-2 text-right font-mono text-[11px] font-normal tracking-wide text-ink/70"
            >
              W
            </th>
            <th
              scope="col"
              className="px-2 py-2 text-right font-mono text-[11px] font-normal tracking-wide text-ink/70"
            >
              L
            </th>
            <th
              scope="col"
              className="px-2 py-2 text-right font-mono text-[11px] font-normal tracking-wide text-ink/70"
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
                className={
                  isMine
                    ? `${tableRowClasses(i, { rowCount: standings.length })} border-l-4 border-l-court bg-court/[0.06]`
                    : tableRowClasses(i, { rowCount: standings.length })
                }
              >
                <td className="px-2 py-2 text-right font-mono text-sm tabular-nums text-ink">{team.rank}</td>
                <td className="px-2 py-1 text-ink">
                  {team.name}
                  {isMine && (
                    <span className="ml-2 inline-flex items-center gap-1.5 font-mono text-[0.65rem] uppercase tracking-wide text-ink">
                      <span className="h-1.5 w-1.5 rounded-full bg-court" aria-hidden="true" />
                      Your team
                    </span>
                  )}
                </td>
                <td className="px-2 py-2 text-right font-mono text-sm tabular-nums text-ink">{team.wins}</td>
                <td className="px-2 py-2 text-right font-mono text-sm tabular-nums text-ink">{team.losses}</td>
                <td className="px-2 py-2 text-right font-mono text-sm tabular-nums text-ink">{team.ties}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
