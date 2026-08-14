import { Bar, BarChart, Cell, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { CHART_COLORS, ChartEmptyState } from "./chartTheme";

export interface AvailabilityChartProps {
  rawProjectedGames: number | null;
  injuryAdjustedGames: number | null;
}

const FULL_SEASON_GAMES = 82;

/** Compact column chart: raw projected games vs. injury-adjusted games vs.
 * an 82-game full-season reference bar, so the injury discount reads as a
 * visible gap rather than two numbers the reader has to subtract manually. */
export function AvailabilityChart({ rawProjectedGames, injuryAdjustedGames }: AvailabilityChartProps) {
  if (rawProjectedGames === null || injuryAdjustedGames === null) {
    return <ChartEmptyState label="Games availability" />;
  }

  const data = [
    { label: "Projected", games: rawProjectedGames, fill: CHART_COLORS.amber },
    { label: "Injury-adj.", games: injuryAdjustedGames, fill: CHART_COLORS.teal },
    { label: "Full season", games: FULL_SEASON_GAMES, fill: CHART_COLORS.reference },
  ];

  return (
    <figure className="m-0">
      <figcaption className="mb-1 text-xs font-medium text-slate-400">Projected games availability</figcaption>
      <div
        role="img"
        aria-label={`Bar chart comparing ${rawProjectedGames.toFixed(0)} raw projected games, ${injuryAdjustedGames.toFixed(0)} injury-adjusted games, and an 82-game full season`}
      >
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
            <XAxis dataKey="label" tick={{ fill: CHART_COLORS.axisText, fontSize: 11 }} stroke={CHART_COLORS.grid} />
            <YAxis
              domain={[0, FULL_SEASON_GAMES]}
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
                <Cell key={d.label} fill={d.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="sr-only">
        {data.map((d) => (
          <li key={d.label} data-testid="availability-bar">
            {d.label}: {d.games} games
          </li>
        ))}
      </ul>
    </figure>
  );
}
