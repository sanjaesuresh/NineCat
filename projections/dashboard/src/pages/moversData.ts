import type { Player } from "../lib/types";

/** One row in a Movers section: the player plus the section-specific driving
 * number rendered as plain text (Movers.tsx stays a thin view over this). */
export interface MoverEntry {
  player: Player;
  detail: string;
}

const TOP_N = 8;
const RANK_DIFF_THRESHOLD = 15;
const INJURY_DROP_THRESHOLD = 5;
const ROLE_CHANGE_THRESHOLD = 0.05;

function formatSigned(value: number, digits = 1): string {
  const rounded = Number(value.toFixed(digits));
  return rounded > 0 ? `+${rounded.toFixed(digits)}` : rounded.toFixed(digits);
}

/** Dense 1..N rank of `players` by `valueOf` descending, ties broken by
 * player_id (deterministic, mirrors recompute.ts's tie-break) so the injury
 * discount gap between the two rankings is stable across renders. */
function rankByDesc(players: Player[], valueOf: (p: Player) => number): Map<string, number> {
  const sorted = [...players].sort((a, b) => {
    const diff = valueOf(b) - valueOf(a);
    if (diff !== 0) return diff;
    return a.player_id < b.player_id ? -1 : a.player_id > b.player_id ? 1 : 0;
  });
  const ranks = new Map<string, number>();
  sorted.forEach((player, index) => ranks.set(player.player_id, index + 1));
  return ranks;
}

/** One player with a real (non-null) consensus gap, narrowed via a plain
 * loop rather than a type-predicate filter -- avoids both the intersection-
 * type predicate and the non-null assertions that reading rank_difference/
 * consensus_rank back off `Player` after filtering would otherwise need. */
interface ConsensusGap {
  player: Player;
  rankDifference: number;
  consensusRank: number;
}

function consensusGaps(players: Player[]): ConsensusGap[] {
  const gaps: ConsensusGap[] = [];
  for (const player of players) {
    const { rank_difference, consensus_rank } = player.consensus;
    if (rank_difference !== null && consensus_rank !== null) {
      gaps.push({ player, rankDifference: rank_difference, consensusRank: consensus_rank });
    }
  }
  return gaps;
}

/**
 * Model Risers: the model ranks these players well above (numerically
 * better than) consensus. consensus.rank_difference >= 15 is the same
 * "worth calling out" threshold badges.tsx's RankDeltaMarker uses.
 */
export function modelRisers(players: Player[]): MoverEntry[] {
  return consensusGaps(players)
    .filter((gap) => gap.rankDifference >= RANK_DIFF_THRESHOLD)
    .sort((a, b) => b.rankDifference - a.rankDifference)
    .slice(0, TOP_N)
    .map(({ player, consensusRank }) => ({
      player,
      detail: `#${player.model.final_rank} model vs #${Math.round(consensusRank)} consensus`,
    }));
}

/** Model Fallers: the mirror of modelRisers -- the model ranks these players
 * well below consensus (rank_difference <= -15). */
export function modelFallers(players: Player[]): MoverEntry[] {
  return consensusGaps(players)
    .filter((gap) => gap.rankDifference <= -RANK_DIFF_THRESHOLD)
    .sort((a, b) => a.rankDifference - b.rankDifference)
    .slice(0, TOP_N)
    .map(({ player, consensusRank }) => ({
      player,
      detail: `#${player.model.final_rank} model vs #${Math.round(consensusRank)} consensus`,
    }));
}

/**
 * Injury Discounts: players who rank far worse once availability is priced
 * in. Ranks the full pool by raw per-game value and by availability-adjusted
 * value separately, then surfaces the largest positive gap (availRank -
 * pgRank) -- a bigger number means a bigger fall once games missed count
 * against them.
 */
export function injuryDiscounts(players: Player[]): MoverEntry[] {
  const perGameRanks = rankByDesc(players, (p) => p.fantasy.per_game_value);
  const availRanks = rankByDesc(players, (p) => p.fantasy.availability_adjusted_value);

  // both maps are built from this same `players` array, so every id is
  // guaranteed present -- a plain loop with an explicit skip (rather than a
  // non-null assertion on the lookup) makes that guarantee visible instead
  // of just asserted away
  const drops: { player: Player; perGameRank: number; availRank: number; drop: number }[] = [];
  for (const player of players) {
    const perGameRank = perGameRanks.get(player.player_id);
    const availRank = availRanks.get(player.player_id);
    if (perGameRank === undefined || availRank === undefined) continue;
    drops.push({ player, perGameRank, availRank, drop: availRank - perGameRank });
  }

  return drops
    .filter((entry) => entry.drop >= INJURY_DROP_THRESHOLD)
    .sort((a, b) => b.drop - a.drop)
    .slice(0, TOP_N)
    .map(({ player, perGameRank, availRank, drop }) => ({
      player,
      detail: `−${drop} spots to availability rank (#${perGameRank} → #${availRank})`,
    }));
}

/** True once at least one player in the pool has a playoff-schedule
 * contribution at all (regardless of sign) -- distinguishes "the 2026-27
 * schedule isn't published yet" (every value undefined) from "published,
 * but nobody clears the boost threshold this cycle" (values present, all <= 0). */
export function playoffDataAvailable(players: Player[]): boolean {
  return players.some((player) => player.model.component_contributions.playoff_schedule !== undefined);
}

/** Playoff Boosts: players whose playoff schedule is most favorably weighted
 * into their composite score. Requires a positive contribution so a merely
 * neutral schedule doesn't crowd out real boosts. */
export function playoffBoosts(players: Player[]): MoverEntry[] {
  const withContribution: { player: Player; contribution: number }[] = [];
  for (const player of players) {
    const contribution = player.model.component_contributions.playoff_schedule;
    if (contribution !== undefined && contribution > 0) {
      withContribution.push({ player, contribution });
    }
  }

  return withContribution
    .sort((a, b) => b.contribution - a.contribution)
    .slice(0, TOP_N)
    .map(({ player, contribution }) => ({
      player,
      detail: `+${contribution.toFixed(2)} playoff schedule contribution`,
    }));
}

/**
 * Breakouts: the largest positive role-change signals -- more minutes/usage
 * than last season's line supports. Secondary sort by minutes_delta desc so
 * two players with an identical role_change_score land in a stable, minutes
 * driven order rather than whatever order the input happened to arrive in.
 */
export function breakouts(players: Player[]): MoverEntry[] {
  return players
    .filter((p) => p.role.role_change_score > ROLE_CHANGE_THRESHOLD)
    .sort((a, b) => {
      const scoreDiff = b.role.role_change_score - a.role.role_change_score;
      if (scoreDiff !== 0) return scoreDiff;
      return b.role.minutes_delta - a.role.minutes_delta;
    })
    .slice(0, TOP_N)
    .map((player) => ({
      player,
      detail: `${formatSigned(player.role.role_change_score, 2)} role change score, ${formatSigned(player.role.minutes_delta, 1)} min`,
    }));
}

export interface MoversData {
  risers: MoverEntry[];
  fallers: MoverEntry[];
  injuryDiscounts: MoverEntry[];
  playoffBoosts: MoverEntry[];
  playoffDataAvailable: boolean;
  breakouts: MoverEntry[];
}

/** Computes every Movers section in one pass over `players` -- the shipped
 * dataset ranking, unfiltered by the Rankings page's filter bar (movers are
 * a pipeline-wide view, not a filtered one). */
export function computeMovers(players: Player[]): MoversData {
  return {
    risers: modelRisers(players),
    fallers: modelFallers(players),
    injuryDiscounts: injuryDiscounts(players),
    playoffBoosts: playoffBoosts(players),
    playoffDataAvailable: playoffDataAvailable(players),
    breakouts: breakouts(players),
  };
}
