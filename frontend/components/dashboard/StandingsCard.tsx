import type { StandingsEntry } from "@/lib/api";

export default function StandingsCard({
  standings,
  highlightTeamName,
}: {
  standings: StandingsEntry[];
  // best-effort: the overview contract doesn't mark which team is the caller's,
  // so callers pass the current matchup's first team name as a heuristic match
  highlightTeamName?: string;
}) {
  if (standings.length === 0) {
    return (
      <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
        Standings aren&apos;t available yet.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto border border-rule">
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">League standings</caption>
        <thead>
          <tr className="border-b-2 border-ink">
            <th scope="col" className="px-2 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70">
              Rank
            </th>
            <th scope="col" className="px-2 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70">
              Team
            </th>
            <th scope="col" className="px-2 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70">
              W
            </th>
            <th scope="col" className="px-2 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70">
              L
            </th>
            <th scope="col" className="px-2 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70">
              T
            </th>
          </tr>
        </thead>
        <tbody>
          {standings.map((team) => {
            const isMine = highlightTeamName !== undefined && team.name === highlightTeamName;
            return (
              <tr
                key={team.team_id}
                className={`border-b border-rule last:border-b-0 ${isMine ? "border-l-4 border-l-court bg-court/[0.06]" : ""}`}
              >
                <td className="px-2 py-2 font-mono text-sm text-ink">{team.rank}</td>
                <td className="px-2 py-2 text-ink">
                  {team.name}
                  {isMine && (
                    <span className="ml-2 inline-flex items-center gap-1.5 font-mono text-[0.65rem] uppercase tracking-wide text-ink">
                      <span className="h-1.5 w-1.5 rounded-full bg-court" aria-hidden="true" />
                      Your team
                    </span>
                  )}
                </td>
                <td className="px-2 py-2 text-center font-mono text-sm text-ink">{team.wins}</td>
                <td className="px-2 py-2 text-center font-mono text-sm text-ink">{team.losses}</td>
                <td className="px-2 py-2 text-center font-mono text-sm text-ink">{team.ties}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
