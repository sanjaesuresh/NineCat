import { Bar, BarChart, Cell, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { CHART_COLORS, ChartEmptyState, weekRowTint } from "./chartTheme";

export interface PlayoffWeeksProps {
  weekGames: Record<string, number> | null;
}

const TINT_FILL: Record<ReturnType<typeof weekRowTint>, string> = {
  favorable: CHART_COLORS.teal,
  unfavorable: CHART_COLORS.rose,
  neutral: CHART_COLORS.neutralBar,
};

/** Games-per-week bar chart from schedule.week_games. week_games is null
 * whenever the season's schedule hasn't been published yet -- render the
 * shared empty state instead of a chart with fabricated zero bars. */
export function PlayoffWeeks({ weekGames }: PlayoffWeeksProps) {
  if (!weekGames || Object.keys(weekGames).length === 0) {
    return <ChartEmptyState label="Playoff weeks" />;
  }

  const data = Object.entries(weekGames)
    .map(([week, games]) => ({ week: Number(week), label: `Wk ${week}`, games }))
    .sort((a, b) => a.week - b.week);

  return (
    <figure className="m-0">
      <figcaption className="mb-1 text-xs font-medium text-slate-400">Games per playoff week</figcaption>
      <div role="img" aria-label="Bar chart of projected games per fantasy playoff week">
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
            <XAxis dataKey="label" tick={{ fill: CHART_COLORS.axisText, fontSize: 11 }} stroke={CHART_COLORS.grid} />
            <YAxis
              allowDecimals={false}
              tick={{ fill: CHART_COLORS.axisText, fontSize: 11 }}
              stroke={CHART_COLORS.grid}
              label={{
                value: "Games",
                angle: -90,
                position: "insideLeft",
                fill: CHART_COLORS.axisText,
                fontSize: 11,
              }}
            />
            <Bar dataKey="games" isAnimationActive={false} radius={2}>
              {data.map((d) => (
                <Cell key={d.week} fill={TINT_FILL[weekRowTint(d.games)]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="sr-only">
        {data.map((d) => (
          <li key={d.week} data-testid="playoff-week-bar">
            Week {d.week}: {d.games} games
          </li>
        ))}
      </ul>
    </figure>
  );
}
