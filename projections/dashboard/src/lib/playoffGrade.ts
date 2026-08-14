/** Letter grade + games total for a player's currently-selected playoff
 * window (Player.schedule.week_games, already swapped to the user's chosen
 * window by App.tsx's applyWindow before this module ever sees it). */
export interface PlayoffGrade {
  grade: string;
  total: number;
}

/** Shared weekly-games arithmetic that both the grade and its sort value
 * derive from. Any missing week (schedule not yet published for that week)
 * makes the whole window's grade unknowable, not just that week, so a single
 * null value bails the whole thing to null rather than skipping the week. */
function weekStats(
  weekGames: Record<string, number | null> | null,
): { total: number; spread: number; avg: number } | null {
  if (!weekGames) return null;
  const values = Object.values(weekGames);
  if (values.length === 0) return null;
  if (values.some((v) => v === null)) return null;

  const games = values as number[];
  const total = games.reduce((sum, g) => sum + g, 0);
  const spread = Math.max(...games) - Math.min(...games);
  return { total, spread, avg: total / games.length };
}

/**
 * Letter grade (avg games/week, A-F) + consistency modifier (+/-/plain from
 * week-to-week spread) for a playoff schedule window -- mirrors 9cat-community
 * grading conventions. F never carries a modifier: a bad average schedule
 * isn't "improved" by being evenly bad.
 */
export function gradePlayoffSchedule(weekGames: Record<string, number | null> | null): PlayoffGrade | null {
  const stats = weekStats(weekGames);
  if (stats === null) return null;

  const { total, spread, avg } = stats;
  const letter = avg >= 3.5 ? "A" : avg >= 3.0 ? "B" : avg >= 2.5 ? "C" : avg >= 2.0 ? "D" : "F";
  const modifier = letter === "F" ? "" : spread === 0 ? "+" : spread === 1 ? "" : "-";
  return { grade: `${letter}${modifier}`, total };
}

/** "A+ (12)" display string; null renders as an em-dash to match the
 * dashboard's other "unknown, not zero" numeric cells (formatNumber/formatValue
 * in columns.tsx). */
export function formatGrade(grade: PlayoffGrade | null): string {
  return grade === null ? "—" : `${grade.grade} (${grade.total})`;
}

/** Sort key: total games first, spread as a tiebreak so two equal-total
 * schedules order more-consistent-first (matches the grade's own +/- modifier
 * ordering). The 0.1 weight can only ever break an exact-total tie, never
 * reorder by total (spread is always a small integer, so 0.1 * spread < 1).
 * Returns null for an ungradeable schedule -- callers apply the table's
 * existing nulls-last convention (see columns.tsx's sortPlayers). */
export function playoffGradeSortValue(weekGames: Record<string, number | null> | null): number | null {
  const stats = weekStats(weekGames);
  return stats === null ? null : stats.total - stats.spread * 0.1;
}
