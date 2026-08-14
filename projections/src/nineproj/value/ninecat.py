"""9-cat valuation: per-game value, availability-adjusted value, scarcity, punt values (Task 10).

Thin composition over the battle-tested ninecat.engine.zscores engine -- every
z-score is computed by compute_player_zscores; nothing here recomputes fantasy
category math. Pure functions, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from ninecat.engine.zscores import CATEGORIES, PlayerAverages, compute_player_zscores

from nineproj.config import Settings
from nineproj.data.universe import PlayerRecord
from nineproj.models.availability import Availability
from nineproj.models.roles import AdjustedProjection
from nineproj.utils.stats import population_zscores

# the 11 counting/shooting fields every AdjustedProjection carries, in the
# order PlayerAverages expects them as kwargs
_STAT_FIELDS: tuple[str, ...] = (
    "fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov",
)

# category_scarcity_weights' own default when called standalone (e.g. tests);
# value_pool below passes settings.scarcity_z_threshold explicitly instead
_SCARCITY_THRESHOLD = 1.0


@dataclass(frozen=True)
class PlayerValue:
    """Everything the explanation layer needs about one player's 9-cat value."""

    per_game_zscores: dict[str, float]
    per_game_value: float
    availability_adjusted_zscores: dict[str, float]
    availability_adjusted_value: float
    scarcity_score: float
    punt_values: dict[str, float]
    position_scarcity_context: dict[str, int]


def _player_averages(
    pid: str, proj: AdjustedProjection, games: float, multiplier: float
) -> PlayerAverages:
    """Build the engine's input row for one player at one games/multiplier pair.

    multiplier=1 for the per-game pass (games is just metadata there);
    multiplier=injury_adjusted_games for the totals pass, so attempts (and
    therefore the volume-weighted FG%/FT% impact) scale with expected games.
    """
    stats = {field: getattr(proj, field) * multiplier for field in _STAT_FIELDS}
    return PlayerAverages(player_key=pid, games=games, **stats)


def category_scarcity_weights(
    per_game_zscores_by_player: dict[str, dict[str, float]],
    *,
    threshold: float = _SCARCITY_THRESHOLD,
) -> dict[str, float]:
    """Per-category scarcity weight: fewer players clearing `threshold` -> higher weight.

    raw_weight_c = 1/(1+n_c) is always in (0, 1], so normalizing to a mean of 1
    across the 9 categories never divides by zero.
    """
    if not per_game_zscores_by_player:
        return dict.fromkeys(CATEGORIES, 1.0)

    raw_weights: dict[str, float] = {}
    for category in CATEGORIES:
        n_c = sum(
            1
            for zscores in per_game_zscores_by_player.values()
            if zscores[category] >= threshold
        )
        raw_weights[category] = 1.0 / (1 + n_c)

    mean_raw = sum(raw_weights.values()) / len(CATEGORIES)
    return {category: raw_weights[category] / mean_raw for category in CATEGORIES}


def _scarcity_raw(zscores: dict[str, float], weights: dict[str, float]) -> float:
    # only a player's strengths (positive z) count toward scarcity credit;
    # being merely average-or-below in a scarce category earns nothing
    return sum(max(zscores[category], 0.0) * weights[category] for category in CATEGORIES)


def _position_scarcity_context(
    pids: list[str],
    per_game_value: dict[str, float],
    records: dict[str, PlayerRecord],
) -> dict[str, int]:
    """Count of above-median (per-game value) players eligible for each slot class.

    A pid with no PlayerRecord (not yet backfilled into the universe) still
    counts toward UTIL, since every player can fill a UTIL slot.
    """
    pool_median = median(per_game_value[pid] for pid in pids)
    counts: dict[str, int] = {}
    for pid in pids:
        if per_game_value[pid] <= pool_median:
            continue
        record = records.get(pid)
        classes = record.slot_classes if record is not None else frozenset({"UTIL"})
        for slot in classes:
            counts[slot] = counts.get(slot, 0) + 1
    return counts


def value_pool(
    projections: dict[str, AdjustedProjection],
    availabilities: dict[str, Availability],
    records: dict[str, PlayerRecord],
    settings: Settings,
) -> dict[str, PlayerValue]:
    """9-cat valuation for a candidate pool: per-game, availability-adjusted, scarcity, punt.

    `settings` is accepted (not settings.json-driven thresholds live in the
    brief as fixed constants) so the caller's Settings object stays the single
    argument threaded through every stage of the pipeline.
    """
    pids = list(projections.keys())

    # pass 1: per-game rates (games=1 is metadata only -- the engine doesn't
    # use it, but it keeps the PlayerAverages row honest about its window)
    per_game_players = [
        _player_averages(pid, projections[pid], games=1.0, multiplier=1.0) for pid in pids
    ]
    per_game_zscores_by_player = compute_player_zscores(per_game_players)

    # pass 2: season totals (per-game stats x injury_adjusted_games), so the
    # volume-weighted FG%/FT% impact and every counting stat reflect how much
    # of the season this player is actually projected to play
    totals_players = [
        _player_averages(
            pid,
            projections[pid],
            games=float(availabilities[pid].injury_adjusted_games),
            multiplier=float(availabilities[pid].injury_adjusted_games),
        )
        for pid in pids
    ]
    totals_zscores_by_player = compute_player_zscores(totals_players)

    per_game_value = {
        pid: sum(per_game_zscores_by_player[pid].values()) for pid in pids
    }
    availability_adjusted_value = {
        pid: sum(totals_zscores_by_player[pid].values()) for pid in pids
    }

    weights = category_scarcity_weights(
        per_game_zscores_by_player, threshold=settings.scarcity_z_threshold
    )
    raw_scarcity = [
        _scarcity_raw(per_game_zscores_by_player[pid], weights) for pid in pids
    ]
    scarcity_scores = dict(zip(pids, population_zscores(raw_scarcity)))

    # shared reference across every player in the pool (documented convention,
    # not a bug) -- it's pool-level context, not a per-player quantity
    position_context = _position_scarcity_context(pids, per_game_value, records)

    result: dict[str, PlayerValue] = {}
    for pid in pids:
        pg_z = per_game_zscores_by_player[pid]
        punt_values = {
            category: per_game_value[pid] - pg_z[category] for category in CATEGORIES
        }
        result[pid] = PlayerValue(
            per_game_zscores=pg_z,
            per_game_value=per_game_value[pid],
            availability_adjusted_zscores=totals_zscores_by_player[pid],
            availability_adjusted_value=availability_adjusted_value[pid],
            scarcity_score=scarcity_scores[pid],
            punt_values=punt_values,
            position_scarcity_context=position_context,
        )
    return result
