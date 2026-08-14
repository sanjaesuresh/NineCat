import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import type { Player } from "../../lib/types";
import { modelFallers, modelRisers } from "../../pages/moversData";
import { CHART_COLORS, ChartEmptyState } from "./chartTheme";

export interface DisagreementChartProps {
  players: Player[];
}

interface DisagreementRow {
  key: string;
  name: string;
  /** Short form for the Y-axis tick -- mirrors RankCompare's shortenLabel;
   * the sr-only list below still uses the untruncated `name`. */
  shortName: string;
  modelRank: number;
  consensusRank: number;
  rankDifference: number;
}

const MAX_AXIS_LABEL = 16;
const TOP_N = 12;

function shortenLabel(label: string): string {
  return label.length > MAX_AXIS_LABEL ? `${label.slice(0, MAX_AXIS_LABEL - 1)}…` : label;
}

/**
 * Horizontal grouped-bar view of where the model disagrees most with
 * consensus: model_rank (teal) paired against the rounded consensus_rank
 * (amber) for the union of Model Risers + Model Fallers -- both of those
 * moversData.ts lists already apply the +-15 rank_difference "worth calling out"
 * threshold, so this chart can't drift from the sections it sits above. The
 * union is re-sorted by |rank_difference| so the biggest disagreements lead
 * regardless of direction, then capped at the top 12 so the chart stays
 * readable even when both lists are near-full.
 */
export function DisagreementChart({ players }: DisagreementChartProps) {
  const candidates = [...modelRisers(players), ...modelFallers(players)].map((entry) => entry.player);

  const rows: DisagreementRow[] = [...candidates]
    .sort((a, b) => Math.abs(b.consensus.rank_difference!) - Math.abs(a.consensus.rank_difference!))
    .slice(0, TOP_N)
    .map((player) => ({
      key: player.player_id,
      name: player.name,
      shortName: shortenLabel(player.name),
      modelRank: player.model.model_rank,
      // consensus_rank is a weighted blend across sources, so real data lands
      // on values like 2.9999999999999996 -- round before it reaches the bar
      // length or the sr-only label (mirrors RankCompare's same fix)
      consensusRank: Math.round(player.consensus.consensus_rank!),
      rankDifference: player.consensus.rank_difference!,
    }));

  if (rows.length === 0) return <ChartEmptyState label="Model vs. consensus disagreement" />;

  // two bars per row need more vertical room than RankCompare's single-bar
  // rows -- 30px/row keeps both bars and their gap legible up to the 12-row cap
  const height = Math.min(380, Math.max(220, 40 + rows.length * 30));

  return (
    <figure className="m-0 min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4">
      <figcaption className="mb-1 text-sm font-semibold text-slate-100">
        Where the model disagrees most with consensus
        <span className="ml-2 text-xs font-normal text-slate-500">(lower rank is better)</span>
      </figcaption>
      <div className="mb-2 flex items-center gap-4 text-xs text-slate-400">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ backgroundColor: CHART_COLORS.teal }} />
          Model rank
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ backgroundColor: CHART_COLORS.amber }} />
          Consensus rank
        </span>
      </div>
      <div
        role="img"
        aria-label="Grouped bar chart pairing each player's model rank against their consensus rank, for the players where the model disagrees most with consensus; lower rank is better"
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
              dataKey="shortName"
              width={96}
              // force every row's tick to render -- same fix as RankCompare's
              // YAxis, recharts otherwise skips alternating ticks once rows
              // get dense
              interval={0}
              tick={{ fill: CHART_COLORS.axisText, fontSize: 10 }}
              stroke={CHART_COLORS.grid}
            />
            <Bar dataKey="modelRank" name="Model rank" fill={CHART_COLORS.teal} isAnimationActive={false} radius={2} />
            <Bar dataKey="consensusRank" name="Consensus rank" fill={CHART_COLORS.amber} isAnimationActive={false} radius={2} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="sr-only">
        {rows.map((r) => (
          <li key={r.key} data-testid="disagreement-chart-row">
            {r.name}: model rank {r.modelRank}, consensus rank {r.consensusRank}
          </li>
        ))}
      </ul>
    </figure>
  );
}
