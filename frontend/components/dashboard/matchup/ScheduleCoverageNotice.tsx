import type { ScheduleCoverage } from "@/lib/api";
import { formatGamesCount } from "@/components/dashboard/format";

/**
 * Shown INSTEAD of the projected scoreboard when schedule_coverage.ok is
 * false. Zero games found for a side means every projected category total
 * would be a real "0" — indistinguishable from a genuine 0-0 tie unless
 * flagged — so rendering that as a confident scoreboard would be actively
 * misleading. This replaces the numbers with an explanation rather than
 * caveating them, per the plan's honesty requirement.
 */
export default function ScheduleCoverageNotice({ coverage }: { coverage: ScheduleCoverage }) {
  return (
    <div role="status" className="border-l-4 border-amber bg-ink/[0.03] px-4 py-4">
      <p className="text-ink">
        Schedule data is missing for this week, so a projection would show every category as
        zero. We&apos;re not showing that as a real scoreboard.
      </p>
      <p className="mt-2 text-sm text-ink/80">
        This should fill in once the league&apos;s schedule data next syncs.
      </p>
      <p className="mt-2 font-mono text-xs uppercase tracking-wide text-ink/70">
        Games found this week — You: {formatGamesCount(coverage.mine_games)}
        {coverage.opponent_games !== null &&
          ` · Opponent: ${formatGamesCount(coverage.opponent_games)}`}
      </p>
    </div>
  );
}
