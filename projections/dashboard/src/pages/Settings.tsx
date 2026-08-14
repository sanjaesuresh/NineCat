import { useEffect, useMemo, useState } from "react";
import { applyWindow, extractDefaultWeights, recomputeScores, type RankedPlayer } from "../lib/recompute";
import type { ComponentKey, CompositeWeights, Dataset } from "../lib/types";

export interface SettingsProps {
  dataset: Dataset;
  // weights/window are lifted to App (single source of truth, shared with the
  // Rankings tab's own recompute) so this page's preview and the main table's
  // re-rank always agree, instead of each owning an independent copy
  weights: CompositeWeights;
  onWeightsChange: (weights: CompositeWeights) => void;
  windowKey: string;
}

const WEIGHT_ROWS: { key: ComponentKey; label: string }[] = [
  { key: "per_game", label: "Per-game production" },
  { key: "availability_adjusted", label: "Availability-adjusted" },
  { key: "expected_games", label: "Expected games" },
  { key: "role_usage", label: "Role / usage" },
  { key: "playoff_schedule", label: "Playoff schedule" },
  { key: "consensus", label: "Consensus" },
  { key: "team_environment", label: "Team environment" },
  { key: "category_scarcity", label: "Category scarcity" },
];

const TOP_N = 25;
const BIGGEST_MOVERS_N = 5;
// recomputing 200 players' scores on every pixel of drag would jank the UI
const RECOMPUTE_DEBOUNCE_MS = 150;

function formatWeight(value: number): string {
  return value.toFixed(2);
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

interface RankShift {
  ranked: RankedPlayer;
  delta: number; // positive == moved up (better) vs the shipped final_rank
}

/** Small up/down marker for a rank shift, styled like badges.tsx's
 * RankDeltaMarker (emerald up / rose down, glyph + sr-only text) but with no
 * magnitude threshold -- every non-zero shift here is something the user's
 * own slider change caused, not just a "large enough to flag" disagreement. */
function RankShiftMarker({ delta }: { delta: number }) {
  if (delta === 0) {
    return <span className="text-slate-600">--</span>;
  }
  const improved = delta > 0;
  return (
    <span className={`inline-flex items-center gap-1 font-semibold ${improved ? "text-emerald-400" : "text-rose-400"}`}>
      <span aria-hidden="true">{improved ? "▲" : "▼"}</span>
      <span>{Math.abs(delta)}</span>
      <span className="sr-only">{improved ? "spots better than shipped rank" : "spots worse than shipped rank"}</span>
    </span>
  );
}

/**
 * Settings page (Task 18): the model-weights lab. Sliders drive a debounced
 * client-side recomputeScores over the full dataset so users can see how
 * shifting emphasis between the 8 composite components reorders the board,
 * without touching the Python pipeline that actually produced the shipped
 * ranking (regular/playoff split, baseline blend, injury shrinkage all stay
 * read-only here -- see the note below the split panel).
 */
export function Settings({ dataset, weights, onWeightsChange, windowKey }: SettingsProps) {
  const defaultWeights = useMemo(() => extractDefaultWeights(dataset), [dataset]);
  const [debouncedWeights, setDebouncedWeights] = useState<CompositeWeights>(weights);

  // debounce so recomputeScores (O(n log n) over 200 players) runs once per
  // pause in dragging, not once per input event
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedWeights(weights), RECOMPUTE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [weights]);

  // the selected playoff window swaps in before this page's own weights
  // recompute -- moving the window dropdown re-ranks the weight-lab preview
  // exactly like it re-ranks the main Rankings table
  const windowedPlayers = useMemo(() => applyWindow(dataset.players, windowKey), [dataset.players, windowKey]);
  const ranked = useMemo(() => recomputeScores(windowedPlayers, debouncedWeights), [windowedPlayers, debouncedWeights]);

  const totalRawWeight = WEIGHT_ROWS.reduce((sum, { key }) => sum + weights[key], 0);

  const shifts: RankShift[] = useMemo(
    () => ranked.map((r) => ({ ranked: r, delta: r.player.model.final_rank - r.newRank })),
    [ranked],
  );

  const top25 = shifts.slice(0, TOP_N);

  const biggestMovers = useMemo(
    () => [...shifts].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, BIGGEST_MOVERS_N),
    [shifts],
  );

  const handleWeightChange = (key: ComponentKey, value: number) => {
    onWeightsChange({ ...weights, [key]: value });
  };

  const handleReset = () => {
    onWeightsChange(defaultWeights);
    setDebouncedWeights(defaultWeights);
  };

  const isDefault = WEIGHT_ROWS.every(({ key }) => weights[key] === defaultWeights[key]);

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-100">Composite weights</h2>
            <p className="mt-1 text-xs text-slate-500">
              Drag a slider to re-rank the full {dataset.players.length}-player board client-side. Effective % is each
              weight&apos;s share of your total slider weight below -- recomputeScores then renormalizes per player over
              only the components that player actually has data for (e.g. no consensus or playoff schedule yet), so an
              individual player&apos;s true weighting can differ slightly from this global share.
            </p>
          </div>
          <button
            type="button"
            onClick={handleReset}
            disabled={isDefault}
            className="min-h-[24px] shrink-0 rounded border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 hover:border-amber-400 hover:text-amber-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Reset to defaults
          </button>
        </div>

        <div className="mt-4 flex flex-col gap-4">
          {WEIGHT_ROWS.map(({ key, label }) => {
            const inputId = `weight-${key}`;
            // slider's accessible description -- lets a screen reader user
            // hear the raw/effective readout without it living inside the label
            const valueId = `${inputId}-value`;
            const effectivePercent = totalRawWeight > 0 ? weights[key] / totalRawWeight : 0;
            return (
              <div key={key} className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <label htmlFor={inputId} className="text-sm text-slate-300">
                    {label}
                  </label>
                  <span id={valueId} className="tabular-nums text-sm text-slate-400">
                    <span className="text-slate-200">{formatWeight(weights[key])}</span> raw &middot;{" "}
                    <span className="text-amber-300">{formatPercent(effectivePercent)}</span> effective
                  </span>
                </div>
                <input
                  id={inputId}
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={weights[key]}
                  onChange={(e) => handleWeightChange(key, Number(e.target.value))}
                  aria-describedby={valueId}
                  className="h-[24px] w-full accent-amber-400"
                />
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="text-sm font-semibold text-slate-100">Regular / playoff split</h2>
        <p className="mt-1 text-sm text-slate-300">
          Regular season{" "}
          <span className="tabular-nums font-medium text-slate-100">
            {formatPercent(dataset.settings.value_split.regular_season)}
          </span>{" "}
          &middot; Playoff{" "}
          <span className="tabular-nums font-medium text-slate-100">
            {formatPercent(dataset.settings.value_split.playoff)}
          </span>
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Read-only. This split, plus other model internals (baseline blend, injury shrinkage) are computed in the
          Python pipeline, not in this UI -- change them in the pipeline config and re-run it to see new numbers here.
        </p>
      </section>

      {biggestMovers.some((m) => m.delta !== 0) && (
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="text-sm font-semibold text-slate-100">Biggest movers under your weights</h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {biggestMovers
              .filter((m) => m.delta !== 0)
              .map((m) => (
                <li
                  key={m.ranked.player.player_id}
                  className="flex items-center gap-2 rounded border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-sm"
                >
                  <span className="text-slate-200">{m.ranked.player.name}</span>
                  <RankShiftMarker delta={m.delta} />
                </li>
              ))}
          </ul>
        </section>
      )}

      <section className="rounded-lg border border-slate-800 bg-slate-900">
        <div className="border-b border-slate-800 px-4 py-2.5">
          <h2 className="text-sm font-semibold text-slate-100">Top 25 under your weights</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            &Delta; is versus the shipped final_rank -- up (green) means your weights rank the player better.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] border-collapse text-sm">
            <caption className="sr-only">Top 25 players re-ranked under the current slider weights.</caption>
            <thead>
              <tr className="border-b border-slate-800 text-xs font-semibold uppercase tracking-wide text-slate-400">
                <th scope="col" className="px-3 py-2 text-right">
                  New #
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  &Delta;
                </th>
                <th scope="col" className="px-3 py-2 text-left">
                  Player
                </th>
                <th scope="col" className="px-3 py-2 text-left">
                  Team
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  New score
                </th>
              </tr>
            </thead>
            <tbody>
              {top25.map(({ ranked: r, delta }, index) => (
                <tr
                  key={r.player.player_id}
                  className={`border-t border-slate-800/60 ${index % 2 === 0 ? "bg-slate-900" : "bg-slate-900/40"}`}
                >
                  <td className="px-3 py-2 text-right tabular-nums text-slate-200">{r.newRank}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <RankShiftMarker delta={delta} />
                  </td>
                  <td className="px-3 py-2 text-slate-100">{r.player.name}</td>
                  <td className="px-3 py-2 text-slate-400">{r.player.team}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-200">{r.newScore.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
