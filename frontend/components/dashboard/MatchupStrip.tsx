import type { Matchup } from "@/lib/api";
import { CATEGORIES } from "@/components/categories";
import { formatStatValue } from "./format";

export default function MatchupStrip({ matchup }: { matchup: Matchup | null }) {
  if (!matchup) {
    return (
      <div className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
        <p>No matchup this week.</p>
        <p className="mt-1 font-mono text-xs text-ink/70">
          This is normal in the offseason or during a league bye.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto border border-rule">
      <table className="w-full border-collapse text-left">
        <caption className="px-3 py-2 text-left font-mono text-xs uppercase tracking-[0.15em] text-ink/70">
          Week {matchup.week} matchup
        </caption>
        <thead>
          <tr className="border-b-2 border-ink">
            <th scope="col" className="px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70">
              Team
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
          {matchup.teams.map((team) => (
            <tr key={team.name} className="border-b border-rule last:border-b-0">
              <td className="px-3 py-2 text-ink">{team.name}</td>
              {CATEGORIES.map((cat) => (
                <td
                  key={cat}
                  className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-sm text-ink"
                >
                  {formatStatValue(cat, team.category_totals?.[cat])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
