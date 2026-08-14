import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import type { CategoryKey } from "../../lib/types";
import { CATEGORY_LABELS, CHART_COLORS, ChartEmptyState, ZSCORE_CATEGORY_ORDER } from "./chartTheme";

export interface CategoryProfileProps {
  zScores: Record<CategoryKey, number> | null;
}

/**
 * Horizontal bar chart of the nine per-game z-scores in the brief's
 * canonical display order (FG%..TO), diverging teal-above/rose-below a
 * reference line at 0. Domain is symmetric around 0 (rounded up to the next
 * whole z, floor of 1) so bars never clip and "average" always sits dead
 * center regardless of which categories this particular player is strong in.
 */
export function CategoryProfile({ zScores }: CategoryProfileProps) {
  if (!zScores) return <ChartEmptyState label="Category z-score profile" />;

  const data = ZSCORE_CATEGORY_ORDER.map((key) => ({ key, label: CATEGORY_LABELS[key], z: zScores[key] }));
  const maxAbs = Math.max(1, ...data.map((d) => Math.ceil(Math.abs(d.z))));

  return (
    <figure className="m-0">
      <figcaption className="mb-1 text-xs font-medium text-slate-400">Category z-score profile</figcaption>
      <div
        role="img"
        aria-label="Bar chart of per-game z-scores across nine fantasy categories, teal above zero and rose below zero"
      >
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, bottom: 16, left: 0 }}>
            <XAxis
              type="number"
              domain={[-maxAbs, maxAbs]}
              tick={{ fill: CHART_COLORS.axisText, fontSize: 11 }}
              stroke={CHART_COLORS.grid}
              label={{
                value: "Z-score",
                position: "insideBottom",
                offset: -4,
                fill: CHART_COLORS.axisText,
                fontSize: 11,
              }}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={36}
              // recharts silently drops alternating category ticks by default
              // once labels get dense (9 rows in ~200px) -- interval={0} forces
              // every one of the nine categories to render, not just every other
              interval={0}
              tick={{ fill: CHART_COLORS.axisText, fontSize: 11 }}
              stroke={CHART_COLORS.grid}
            />
            <ReferenceLine x={0} stroke={CHART_COLORS.reference} />
            <Bar dataKey="z" isAnimationActive={false} radius={2}>
              {data.map((d) => (
                <Cell key={d.key} fill={d.z >= 0 ? CHART_COLORS.teal : CHART_COLORS.rose} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* recharts renders an inert SVG that screen readers can't parse
       * meaningfully -- mirror the same nine values as a visually-hidden
       * list so the underlying data stays accessible (and independently
       * testable) regardless of how/whether the SVG actually painted. */}
      <ul className="sr-only">
        {data.map((d) => (
          <li key={d.key} data-testid="category-profile-bar">
            {d.label}: {d.z.toFixed(2)}
          </li>
        ))}
      </ul>
    </figure>
  );
}
