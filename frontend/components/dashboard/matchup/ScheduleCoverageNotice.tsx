import type { ScheduleCoverage } from "@/lib/api";
import { formatGamesCount } from "@/components/dashboard/format";
import { captionClasses, proseClasses } from "@/components/dashboard/layout/typography";
import { noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";

/**
 * Shown INSTEAD of the projected scoreboard when schedule_coverage.ok is
 * false. Zero games found for a side means every projected category total
 * would be a real "0" — indistinguishable from a genuine 0-0 tie unless
 * flagged — so rendering that as a confident scoreboard would be actively
 * misleading. This replaces the numbers with an explanation rather than
 * caveating them, per the plan's honesty requirement.
 *
 * `withheld` names what this notice is standing in for. The Adds page reuses
 * this component for its ranked candidate list, and telling that user we're
 * withholding a "scoreboard" describes a screen they never asked for while
 * never saying which thing is actually missing.
 */
export default function ScheduleCoverageNotice({
  coverage,
  withheld = "a real scoreboard",
}: {
  coverage: ScheduleCoverage;
  withheld?: string;
}) {
  return (
    <div role="status" className={noticeClasses()}>
      <span className={noticeDotClasses("warn")} aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-ink">
          Schedule data is missing for this week, so a projection would show every category as
          zero. We&apos;re not showing that as {withheld}.
        </p>
        <p className={`mt-2 ${proseClasses("muted")}`}>
          This should fill in once the league&apos;s schedule data next syncs.
        </p>
        <p className={`mt-2 ${captionClasses()}`}>
          Games found this week — You: {formatGamesCount(coverage.mine_games)}
          {coverage.opponent_games !== null &&
            ` · Opponent: ${formatGamesCount(coverage.opponent_games)}`}
        </p>
      </div>
    </div>
  );
}
