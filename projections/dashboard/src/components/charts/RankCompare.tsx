import { Bar, BarChart, Cell, ResponsiveContainer, XAxis, YAxis } from "recharts";
import type { ConsensusPerSource } from "../../lib/types";
import { CHART_COLORS, ChartEmptyState } from "./chartTheme";

export interface RankCompareProps {
  modelRank: number | null;
  finalRank: number | null;
  consensusRank: number | null;
  perSource: Record<string, ConsensusPerSource>;
}

interface RankRow {
  key: string;
  label: string;
  /** Short form for the Y-axis tick -- real source names run up to ~80
   * characters ("Sports Illustrated (OnSI) Way-Too-Early Top 50 2026-27
   * Rankings (Jun 4, 2026)"), which overlaps every other tick if rendered in
   * full. The sr-only list below still uses the untruncated `label`. */
  shortLabel: string;
  rank: number;
  imputed: boolean;
}

const MAX_AXIS_LABEL = 16;

function shortenLabel(label: string): string {
  return label.length > MAX_AXIS_LABEL ? `${label.slice(0, MAX_AXIS_LABEL - 1)}…` : label;
}

/**
 * Bar comparison of our final rank, the raw model rank, the blended
 * consensus rank, and each named source's rank. Imputed sources (a filled-in
 * placeholder rank, not a real reported one) get a muted/translucent fill
 * plus an "(imputed)" suffix in the sr-only data list rather than a fully
 * saturated bar that would read as equally trustworthy.
 *
 * The axis intentionally stays a plain ascending number line -- reversing it
 * so "better" points right would make bar length read backwards (a long bar
 * would mean a *worse*, higher-numbered rank). "Lower is better" is called
 * out in the caption instead of bending the chart to fake it.
 */
export function RankCompare({ modelRank, finalRank, consensusRank, perSource }: RankCompareProps) {
  const rows: RankRow[] = [
    { key: "final", label: "Our Rank", rank: finalRank, imputed: false },
    { key: "model", label: "Model Rank", rank: modelRank, imputed: false },
    // consensus_rank is a weighted blend across sources, so real data lands
    // on values like 2.9999999999999996 -- round it before it ever reaches
    // the bar length or the sr-only label
    { key: "consensus", label: "Consensus", rank: consensusRank === null ? null : Math.round(consensusRank), imputed: false },
    ...Object.entries(perSource)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([source, info]) => ({ key: source, label: source, rank: info.rank, imputed: info.imputed })),
  ]
    .filter((row): row is Omit<RankRow, "shortLabel"> => row.rank !== null)
    .map((row) => ({ ...row, shortLabel: shortenLabel(row.label) }));

  if (rows.length === 0) return <ChartEmptyState label="Rank comparison" />;

  const height = Math.min(220, Math.max(180, 40 + rows.length * 22));

  return (
    <figure className="m-0">
      <figcaption className="mb-1 text-xs font-medium text-slate-400">
        Rank comparison across sources (lower is better)
      </figcaption>
      <div
        role="img"
        aria-label="Bar chart comparing our rank, model rank, consensus rank, and each source's rank; lower is better"
      >
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, bottom: 16, left: 0 }}>
            <XAxis
              type="number"
              tick={{ fill: CHART_COLORS.axisText, fontSize: 11 }}
              stroke={CHART_COLORS.grid}
              label={{
                value: "Rank (lower is better)",
                position: "insideBottom",
                offset: -4,
                fill: CHART_COLORS.axisText,
                fontSize: 11,
              }}
            />
            <YAxis
              type="category"
              dataKey="shortLabel"
              width={96}
              // force every row's tick to render -- recharts otherwise skips
              // alternating ticks once labels get dense (same issue as
              // CategoryProfile, just triggered by row count here)
              interval={0}
              tick={{ fill: CHART_COLORS.axisText, fontSize: 10 }}
              stroke={CHART_COLORS.grid}
            />
            <Bar dataKey="rank" isAnimationActive={false} radius={2}>
              {rows.map((r) => (
                <Cell key={r.key} fill={r.imputed ? CHART_COLORS.neutralBar : CHART_COLORS.amber} fillOpacity={r.imputed ? 0.55 : 1} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="sr-only">
        {rows.map((r) => (
          <li key={r.key} data-testid="rank-compare-bar">
            {r.label}: {r.rank}
            {r.imputed ? " (imputed)" : ""}
          </li>
        ))}
      </ul>
    </figure>
  );
}
