import type { ComponentKey, CompositeWeights, Dataset, Player } from "./types";

export interface RankedPlayer {
  player: Player;
  newScore: number;
  newRank: number;
}

/** Pulls the pipeline's shipped composite weights out of a loaded dataset, so
 * the UI's initial weight sliders start from what actually produced the
 * dataset's ranking rather than a hardcoded copy that could drift from it. */
export function extractDefaultWeights(dataset: Dataset): CompositeWeights {
  return dataset.settings.composite_weights;
}

/**
 * Per-component contribution (renormalized weight x score) for one player --
 * client-side mirror of nineproj.value.composite.compute_composite's scoring
 * step: renormalize `weights` over only the components that player actually
 * has (null components -- missing schedule/consensus data -- are dropped and
 * the remaining weights redistributed proportionally, exactly as the Python
 * renorm does). Exposed per-component (not just the summed score) so callers
 * like Movers' Playoff Boosts can read one component's contribution under the
 * currently selected window/weights, not just the shipped dataset export.
 */
export function componentContributions(
  player: Player,
  weights: CompositeWeights,
): Partial<Record<ComponentKey, number>> {
  const scores = player.model.component_scores;
  const present = (Object.keys(scores) as ComponentKey[]).filter(
    (key) => scores[key] !== null,
  );

  const weightSum = present.reduce((sum, key) => sum + weights[key], 0);
  // guards a degenerate all-zero-weight selection; Python's equivalent would
  // divide by zero, but custom UI weights can reach this where the shipped
  // settings (which must sum to 1.0) never would
  if (weightSum === 0) {
    return {};
  }

  const result: Partial<Record<ComponentKey, number>> = {};
  for (const key of present) {
    result[key] = (weights[key] / weightSum) * (scores[key] as number);
  }
  return result;
}

function recomputeScore(player: Player, weights: CompositeWeights): number {
  return Object.values(componentContributions(player, weights)).reduce(
    (sum, contribution) => sum + contribution,
    0,
  );
}

/** True when every composite weight in `a` exactly matches `b` -- decides
 * whether the current UI weights are still the shipped defaults (an exact
 * bypass of the recompute pipeline, not just "close enough"). */
export function weightsEqual(a: CompositeWeights, b: CompositeWeights): boolean {
  return (Object.keys(a) as ComponentKey[]).every((key) => a[key] === b[key]);
}

/**
 * Swaps every player's playoff-schedule component (score, plus the schedule/
 * fantasy display fields the UI reads) for one specific playoff-window
 * choice, pulled from schedule.windows[windowKey] -- the pipeline's per-
 * window precompute. Feeds recomputeScores for the re-rank, and also makes
 * RankingsTable's Playoff column, PlayerDetail's schedule section, and the
 * PlayoffWeeks chart show that window's numbers, all from the one transform
 * (missing window data collapses to the same null convention the shipped
 * default fields already use).
 */
export function applyWindow(players: Player[], windowKey: string): Player[] {
  return players.map((player) => {
    const w = player.schedule.windows[windowKey];
    return {
      ...player,
      schedule: {
        ...player.schedule,
        week_games: w?.week_games ?? null,
        playoff_games: w?.playoff_games ?? null,
        playoff_b2bs: w?.playoff_b2bs ?? null,
        playoff_schedule_score: w?.playoff_schedule_score ?? null,
        expected_playoff_games: w?.expected_playoff_games ?? null,
      },
      fantasy: {
        ...player.fantasy,
        playoff_value: w?.playoff_value_z ?? null,
      },
      model: {
        ...player.model,
        component_scores: {
          ...player.model.component_scores,
          playoff_schedule: w?.playoff_value_z ?? null,
        },
      },
    };
  });
}

/**
 * Recomputes every player's score under `weights` and produces a dense
 * re-rank (1..N, no gaps) ordered by score desc, tie-broken by
 * fantasy.per_game_value desc then player_id asc -- matches composite.py's
 * _rank exactly: sorted(pids, key=lambda p: (-score[p], -per_game_value[p], p)).
 */
export function recomputeScores(players: Player[], weights: CompositeWeights): RankedPlayer[] {
  const scored = players.map((player) => ({
    player,
    newScore: recomputeScore(player, weights),
  }));

  scored.sort((a, b) => {
    if (b.newScore !== a.newScore) return b.newScore - a.newScore;
    if (b.player.fantasy.per_game_value !== a.player.fantasy.per_game_value) {
      return b.player.fantasy.per_game_value - a.player.fantasy.per_game_value;
    }
    return a.player.player_id < b.player.player_id ? -1 : a.player.player_id > b.player.player_id ? 1 : 0;
  });

  return scored.map((entry, index) => ({ ...entry, newRank: index + 1 }));
}
