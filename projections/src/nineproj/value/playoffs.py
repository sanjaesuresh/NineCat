"""Playoff-window value blending: schedule-weighted playoff production folded
into a single draft value, on top of the regular-season 9-cat value (Task 11).

`per_game_value` and `availability_adjusted_value` come from `value_pool`
(Task 10); `playoff_profile` per team comes from `nineproj.data.schedule`
(Task 3); `availability_probability` comes from `project_availability`
(Task 8). Pure function, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from nineproj.config import Settings
from nineproj.data.schedule import PlayoffProfile, UnavailableProfile
from nineproj.models.availability import Availability
from nineproj.utils.stats import population_zscores
from nineproj.value.ninecat import PlayerValue


@dataclass(frozen=True)
class PlayoffValue:
    """One player's playoff-window production blended into a combined draft value."""

    expected_playoff_games: float | None
    playoff_value: float | None  # pool-normalized (population z), None when schedule unavailable
    draft_value: float  # availability_adjusted_value carried through unchanged, for display
    regular_season_z: float
    combined_value: float


def _has_schedule(profile: PlayoffProfile | UnavailableProfile | None) -> bool:
    # missing pid or an UnavailableProfile (D6: schedule unpublished) both
    # collapse to "no playoff data for this player"
    return profile is not None and profile.playoff_games is not None


@dataclass(frozen=True)
class WindowPlayoffValue:
    """One player's expected games and standardized playoff-window value for
    ONE playoff-window choice (population z, pool-relative). Both fields are
    None together, exactly when the player has no usable schedule for this window.
    """

    expected_playoff_games: float | None
    playoff_value_z: float | None


def playoff_window_values(
    values: dict[str, PlayerValue],
    availabilities: dict[str, Availability],
    profiles: dict[str, PlayoffProfile | UnavailableProfile],
) -> dict[str, WindowPlayoffValue]:
    """Expected playoff games x standardized playoff value for one window's
    profiles. Shared by playoff_values (the shipped default playoff_window) and
    the pipeline's per-candidate-window loop (dashboard dropdown) so the default
    window's numbers and its "19-21" windows-map entry are literally the same
    computation, not two copies that could drift apart.
    """
    pids = list(values.keys())
    available_pids = [pid for pid in pids if _has_schedule(profiles.get(pid))]

    if not available_pids:
        # D6: the whole league's schedule is unpublished for this window
        return {pid: WindowPlayoffValue(None, None) for pid in pids}

    # availabilities[pid] is a required KeyError, not a silent 1.0 fallback:
    # a pid missing here means an upstream pipeline bug, not "assume healthy"
    expected_games = {
        pid: profiles[pid].playoff_games * availabilities[pid].availability_probability
        for pid in available_pids
    }
    playoff_raw = {pid: values[pid].per_game_value * expected_games[pid] for pid in available_pids}
    playoff_z = dict(
        zip(available_pids, population_zscores([playoff_raw[pid] for pid in available_pids]))
    )

    return {
        pid: (
            WindowPlayoffValue(expected_games[pid], playoff_z[pid])
            if pid in playoff_z
            # this player's own team's schedule is unavailable while others'
            # are known -- individually null, not a fabricated 0
            else WindowPlayoffValue(None, None)
        )
        for pid in pids
    }


def playoff_values(
    values: dict[str, PlayerValue],
    availabilities: dict[str, Availability],
    profiles: dict[str, PlayoffProfile | UnavailableProfile],
    settings: Settings,
) -> dict[str, PlayoffValue]:
    """Blend each player's regular-season value with an availability-weighted
    playoff-window value, both standardized to the same population-z scale so
    settings.value_split's 75/25 weights are combining like with like.
    """
    pids = list(values.keys())

    reg_z = dict(
        zip(pids, population_zscores([values[pid].availability_adjusted_value for pid in pids]))
    )
    window = playoff_window_values(values, availabilities, profiles)

    result: dict[str, PlayoffValue] = {}
    for pid in pids:
        draft_value = values[pid].availability_adjusted_value
        w = window[pid]
        if w.playoff_value_z is None:
            result[pid] = PlayoffValue(
                expected_playoff_games=None,
                playoff_value=None,
                draft_value=draft_value,
                regular_season_z=reg_z[pid],
                combined_value=reg_z[pid],
            )
            continue
        combined = (
            settings.value_split.regular_season * reg_z[pid]
            + settings.value_split.playoff * w.playoff_value_z
        )
        result[pid] = PlayoffValue(
            expected_playoff_games=w.expected_playoff_games,
            playoff_value=w.playoff_value_z,
            draft_value=draft_value,
            regular_season_z=reg_z[pid],
            combined_value=combined,
        )
    return result
