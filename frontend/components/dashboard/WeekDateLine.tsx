import type { WeekRange } from "@/lib/api";
import { formatWeekRange, formatSlotDay } from "@/components/dashboard/matchup/format";
import { captionClasses } from "@/components/dashboard/layout/typography";

/**
 * "Week N · date range [(dates estimated)] · Data as of ..." line, shared by
 * Matchup and Adds -- both pages show the same four fields (week, week_range,
 * as_of) in the same order with the same "dates estimated" caveat, so this
 * exists once rather than drifting across two copies.
 */
export default function WeekDateLine({
  week,
  weekRange,
  asOf,
}: {
  week: number;
  weekRange: WeekRange;
  asOf: string;
}) {
  return (
    <p className={captionClasses()}>
      Week {week} · {formatWeekRange(weekRange.start_date, weekRange.end_date)}
      {weekRange.is_derived && (
        <span className="ml-2 normal-case text-ink-muted">
          (dates estimated — not confirmed by Yahoo)
        </span>
      )}
      {" · "}Data as of {formatSlotDay(asOf)}
    </p>
  );
}
