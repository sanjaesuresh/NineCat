"""Team-environment (pace) adjustment: rescale counting stats for a team
change or a league-wide pace shift (Task 7).

`team_pace_estimates` derives a per-team possession proxy from last season's
SeasonLine data; `apply_environment` applies the capped ratio between a
player's old and new team pace to an AdjustedProjection's counting stats.
Pure functions -- no I/O, no mutation of inputs.
"""

from __future__ import annotations

from dataclasses import replace

from nineproj.config import Settings
from nineproj.data.nba_stats import SeasonLine
from nineproj.models.roles import AdjustedProjection

# the 11 counting/shooting stats a pace change moves proportionally (minutes
# doesn't change with pace -- it's a role/rotation quantity, not a possession one)
_COUNTING_STATS: tuple[str, ...] = (
    "fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov",
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def team_pace_estimates(lines: list[SeasonLine]) -> dict[str, float]:
    """Per-team possession proxy: sum of (fga + 0.44*fta + tov) x games, divided
    by that team's max single-player games total.

    0.44 is the standard estimated-possessions free-throw-trip convention
    (roughly 0.44 FT trips end a possession per FTA); dividing the team-wide
    per-game-stat sum by the team's highest games-played approximates a full
    team-season's possession total scaled back to one team-game.
    """
    possession_sum: dict[str, float] = {}
    max_games: dict[str, int] = {}
    for line in lines:
        team_possessions = (line.fga + 0.44 * line.fta + line.tov) * line.games
        possession_sum[line.team] = possession_sum.get(line.team, 0.0) + team_possessions
        max_games[line.team] = max(max_games.get(line.team, 0), line.games)

    return {
        team: possession_sum[team] / max_games[team]
        for team in possession_sum
        if max_games[team] > 0
    }


def apply_environment(
    adjusted: AdjustedProjection,
    old_pace: float | None,
    new_pace: float | None,
    settings: Settings,
) -> AdjustedProjection:
    """Rescale an AdjustedProjection's counting stats by the capped pace ratio.

    Percentages are preserved automatically since makes and attempts scale by
    the same multiplier. A missing pace on either side (no evidence to compare
    against) leaves the projection unchanged rather than guessing a direction.
    """
    # a non-positive pace on either side isn't a usable ratio input (old_pace
    # would divide by <=0; new_pace<=0 would imply a nonsensical near-zero
    # team) -- pass through unchanged rather than let it silently floor to
    # the pace cap
    if old_pace is None or new_pace is None or old_pace <= 0 or new_pace <= 0:
        return replace(adjusted, pace_multiplier=1.0)

    cap = settings.adjustment_caps.pace_multiplier
    multiplier = _clamp(new_pace / old_pace, 1 - cap, 1 + cap)

    scaled = {stat: getattr(adjusted, stat) * multiplier for stat in _COUNTING_STATS}
    return replace(adjusted, pace_multiplier=multiplier, **scaled)
