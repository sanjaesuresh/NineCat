"""Pure z-score math for the NineCat engine.

This module has no DB access and no dependency on ninecat.models — it defines
the input contract (PlayerAverages) that callers (e.g. the Task 13 API layer)
must adapt their rows to, so the engine stays testable and storage-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass

# canonical 9-cat category order, used everywhere in NineCat (UI, engine, API)
CATEGORIES = ("fg_pct", "ft_pct", "tpm", "pts", "reb", "ast", "stl", "blk", "tov")

# counting categories standardized directly (no volume weighting needed);
# fg_pct/ft_pct are handled separately via the volume-weighted impact method
_COUNTING_FIELDS = ("tpm", "pts", "reb", "ast", "stl", "blk", "tov")


@dataclass(frozen=True)
class PlayerAverages:
    """Per-game averages for one player, over some window (season, projection, etc).

    fgm/fga/ftm/fta are required in addition to the percentages they imply,
    because FG%/FT% z-scores are volume-weighted: a percentage alone can't
    tell a 1-for-1 shooter from a 9-for-10 shooter.
    """

    player_key: str
    games: float
    fgm: float
    fga: float
    ftm: float
    fta: float
    tpm: float
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    tov: float


def _population_std(values: list[float]) -> float:
    """Population standard deviation (divide by N, not N-1) — we treat the
    given players as the whole population being ranked, not a sample of it."""
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return variance**0.5


def _counting_zscores(values: list[float]) -> list[float]:
    std = _population_std(values)
    if std == 0:
        # zero variance (e.g. every player identical, or a 1-player population):
        # z is undefined by the formula, so define it as 0 rather than raising
        return [0.0] * len(values)
    mean = sum(values) / len(values)
    return [(v - mean) / std for v in values]


def _volume_weighted_pct_zscores(makes: list[float], attempts: list[float]) -> list[float]:
    """Standard fantasy volume-weighted percentage method: a player's impact on
    the population's FG%/FT% is (their pct - population pct) * their attempts,
    then that impact is standardized like a counting stat. This is what makes a
    high-volume 80% shooter rank above a low-volume 100% shooter, correctly."""
    total_makes = sum(makes)
    total_attempts = sum(attempts)
    pop_pct = total_makes / total_attempts if total_attempts else 0.0

    impacts = []
    for m, a in zip(makes, attempts):
        if not a:
            # explicit branch (not just a 0.0 player_pct * 0 attempts): the
            # arithmetic form ((0.0 - pop_pct) * 0) can yield IEEE754 -0.0
            # whenever pop_pct > 0, so we return the literal +0.0 instead
            impacts.append(0.0)
            continue
        player_pct = m / a
        impacts.append((player_pct - pop_pct) * a)

    return _counting_zscores(impacts)


def compute_player_zscores(
    players: list[PlayerAverages],
) -> dict[str, dict[str, float]]:
    """Given a player population's per-game averages, return per-player
    per-category z-scores keyed by player_key, then by category (see CATEGORIES).
    """
    if not players:
        return {}

    fg_z = _volume_weighted_pct_zscores([p.fgm for p in players], [p.fga for p in players])
    ft_z = _volume_weighted_pct_zscores([p.ftm for p in players], [p.fta for p in players])
    counting_z = {
        field: _counting_zscores([getattr(p, field) for p in players])
        for field in _COUNTING_FIELDS
    }

    result: dict[str, dict[str, float]] = {}
    for i, player in enumerate(players):
        result[player.player_key] = {
            "fg_pct": fg_z[i],
            "ft_pct": ft_z[i],
            "tpm": counting_z["tpm"][i],
            "pts": counting_z["pts"][i],
            "reb": counting_z["reb"][i],
            "ast": counting_z["ast"][i],
            "stl": counting_z["stl"][i],
            "blk": counting_z["blk"][i],
            # turnovers are bad, so negate: a high-TO player's positive raw z
            # (far from the mean) becomes negative here, keeping "positive = good".
            # + 0.0 normalizes -0.0 (negating an exact-mean player's raw z of
            # 0.0 would otherwise leak IEEE754 negative zero into the output)
            "tov": (-counting_z["tov"][i]) + 0.0,
        }
    return result
