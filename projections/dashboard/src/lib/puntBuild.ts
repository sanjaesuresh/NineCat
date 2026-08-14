import { CATEGORY_LABELS, ZSCORE_CATEGORY_ORDER } from "../components/charts/chartTheme";
import type { CategoryKey, Player } from "./types";

// chartTheme.tsx already owns the one canonical label/order pair for the nine
// categories (columns.tsx, CategoryProfile) -- re-exported here so callers of
// the punt-build feature (App.tsx's header, this module's own tests) have a
// single import to reach for instead of a second copy drifting from it.
export { CATEGORY_LABELS, ZSCORE_CATEGORY_ORDER };

/**
 * Population z-score (mean 0, divide-by-N standard deviation -- not N-1)
 * across `values`, matching nineproj.utils.stats.population_zscores and this
 * dashboard's other re-standardization (recompute.ts's window swap feeds the
 * pipeline's own precomputed per-window z, but the shape is the same
 * convention). Zero variance (every value identical, including an empty or
 * single-element pool) collapses every z to 0 rather than dividing by zero.
 */
export function populationZ(values: number[]): number[] {
  const n = values.length;
  if (n === 0) return [];
  const mean = values.reduce((sum, v) => sum + v, 0) / n;
  const variance = values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / n;
  const std = Math.sqrt(variance);
  if (std === 0) return values.map(() => 0);
  return values.map((v) => (v - mean) / std);
}

function sumCategories(zscores: Record<CategoryKey, number>, categories: CategoryKey[]): number {
  return categories.reduce((sum, cat) => sum + zscores[cat], 0);
}

/**
 * Re-ranks a player pool for a "punt build": drop 1-2 categories from the
 * per-game (and, where available, availability-adjusted) 9-cat sum, then
 * re-standardize the punted sums across the pool so the composite's
 * per_game/availability_adjusted components reflect the smaller category set
 * instead of the shipped full-9cat one.
 *
 * `[]` returns `players` by reference (identity fast-path), mirroring
 * applyWindow/recompute.ts's convention so App.tsx's "shipped order" bypass
 * still works when no punt is selected.
 *
 * APPROXIMATION: the population z is re-standardized over the pool passed in
 * (the dashboard's exported ~200 players), not the pipeline's full draftable
 * universe -- the same approximation every other client-side re-rank in this
 * app already makes (recompute.ts's recomputeScores works the same way).
 *
 * fantasy.availability_adjusted_zscores isn't in the currently-exported
 * dataset (see types.ts) even though the pipeline computes it -- when any
 * player in the pool is missing it, the availability-adjusted swap is skipped
 * for the whole pool (left at its shipped value) rather than guessing; the
 * per-game swap (which the export does carry) still fully applies.
 */
export function applyPuntBuild(players: Player[], punts: CategoryKey[]): Player[] {
  if (punts.length === 0) return players;

  const puntSet = new Set(punts);
  const activeCategories = ZSCORE_CATEGORY_ORDER.filter((cat) => !puntSet.has(cat));

  const perGameSums = players.map((p) => sumCategories(p.fantasy.per_game_zscores, activeCategories));
  const perGameZ = populationZ(perGameSums);

  const hasAvailZ = players.every((p) => p.fantasy.availability_adjusted_zscores !== undefined);
  const availSums = hasAvailZ
    ? players.map((p) => sumCategories(p.fantasy.availability_adjusted_zscores!, activeCategories))
    : null;
  const availZ = availSums ? populationZ(availSums) : null;

  return players.map((player, i) => ({
    ...player,
    fantasy: {
      ...player.fantasy,
      per_game_value: perGameSums[i],
      ...(availSums ? { availability_adjusted_value: availSums[i] } : {}),
    },
    model: {
      ...player.model,
      component_scores: {
        ...player.model.component_scores,
        per_game: perGameZ[i],
        ...(availZ ? { availability_adjusted: availZ[i] } : {}),
      },
    },
  }));
}
