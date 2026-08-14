"""Tests for nineproj.value.playoffs: playoff-window value blending (Task 11)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from nineproj.config import load_settings
from nineproj.data.schedule import PlayoffProfile, UnavailableProfile
from nineproj.models.availability import Availability
from nineproj.value.ninecat import PlayerValue
from nineproj.value.playoffs import playoff_values, playoff_window_values

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


def _settings():
    return load_settings(SHIPPED_SETTINGS)


def _player_value(per_game_value: float, availability_adjusted_value: float) -> PlayerValue:
    # only the two fields playoff_values reads are populated; the rest of
    # PlayerValue's dict fields are irrelevant to this module
    return PlayerValue(
        per_game_zscores={},
        per_game_value=per_game_value,
        availability_adjusted_zscores={},
        availability_adjusted_value=availability_adjusted_value,
        scarcity_score=0.0,
        punt_values={},
        position_scarcity_context={},
    )


def _availability(probability: float) -> Availability:
    return Availability(
        raw_projected_games=70.0,
        injury_risk_score=0.0,
        injury_risk_label="low",
        injury_adjusted_games=70,
        availability_probability=probability,
        confidence=1.0,
    )


def _profile(playoff_games: int) -> PlayoffProfile:
    return PlayoffProfile(
        games_by_week={},
        playoff_games=playoff_games,
        playoff_b2b_count=0,
        playoff_schedule_score=0.5,
    )


def test_bigger_playoff_window_raises_combined_value_as_a_tiebreaker() -> None:
    settings = _settings()

    # A and B are identical in every regular-season respect; only their teams'
    # playoff-window game counts differ (12 vs 9). C is a filler player so the
    # pool has nonzero variance (population z of a single repeated value is
    # degenerate, see test_zero_variance_pool below).
    values = {
        "A": _player_value(per_game_value=5.0, availability_adjusted_value=5.0),
        "B": _player_value(per_game_value=5.0, availability_adjusted_value=5.0),
        "C": _player_value(per_game_value=0.0, availability_adjusted_value=0.0),
    }
    availabilities = {pid: _availability(1.0) for pid in values}
    profiles = {"A": _profile(12), "B": _profile(9), "C": _profile(10)}

    result = playoff_values(values, availabilities, profiles, settings)

    # hand-derived: playoff_raw = per_game_value * playoff_games = {A: 60, B: 45, C: 0}
    # population mean 35, population std sqrt(650); regular_season_z is
    # identical for A and B (equal availability_adjusted_value), so the whole
    # combined-value gap comes from the 0.25-weighted playoff term
    std_playoff = math.sqrt(650)
    expected_gap = 0.25 * (60 - 45) / std_playoff
    actual_gap = result["A"].combined_value - result["B"].combined_value
    assert actual_gap == pytest.approx(expected_gap, abs=1e-6)
    assert actual_gap > 0

    # tiebreaker, not dominator: a hypothetical pair with identical schedules
    # (so their playoff_z terms cancel) but differing by a full 1.0 in
    # regular_season_z would have combined gap == value_split.regular_season
    # (== 0.75*1.0 + 0.25*0) exactly, by the same linear blend this module
    # implements -- the schedule-driven gap above must be smaller than that
    equal_schedule_one_z_gap = settings.value_split.regular_season * 1.0
    assert actual_gap < equal_schedule_one_z_gap


def test_all_profiles_unavailable_falls_back_to_regular_season_only() -> None:
    settings = _settings()
    values = {
        "A": _player_value(per_game_value=5.0, availability_adjusted_value=5.0),
        "B": _player_value(per_game_value=3.0, availability_adjusted_value=1.0),
    }
    availabilities = {pid: _availability(1.0) for pid in values}
    profiles = {pid: UnavailableProfile() for pid in values}

    result = playoff_values(values, availabilities, profiles, settings)

    for pid in values:
        assert result[pid].expected_playoff_games is None
        assert result[pid].playoff_value is None
        # no arithmetic applied on this path -- combined must equal
        # regular_season_z exactly, not merely approximately
        assert result[pid].combined_value == result[pid].regular_season_z


def test_player_missing_from_profiles_falls_back_individually() -> None:
    settings = _settings()
    values = {
        "X": _player_value(per_game_value=1.0, availability_adjusted_value=1.0),
        "Y": _player_value(per_game_value=2.0, availability_adjusted_value=2.0),
        "Z": _player_value(per_game_value=2.0, availability_adjusted_value=3.0),
    }
    # X has no availability entry at all -- proves the unavailable-profile
    # branch never touches it (would KeyError otherwise)
    availabilities = {"Y": _availability(1.0), "Z": _availability(1.0)}
    profiles = {"Y": _profile(10), "Z": _profile(5)}  # X missing entirely

    result = playoff_values(values, availabilities, profiles, settings)

    assert result["X"].expected_playoff_games is None
    assert result["X"].playoff_value is None
    # hand-derived population z of [1, 2, 3]: mean 2, population std sqrt(2/3)
    expected_x_z = (1 - 2) / math.sqrt(2 / 3)
    assert result["X"].regular_season_z == pytest.approx(expected_x_z, abs=1e-6)
    assert result["X"].combined_value == result["X"].regular_season_z

    # Y and Z's playoff population excludes X: playoff_raw = {Y: 20, Z: 10},
    # and a 2-element population z-score is always exactly +-1.0
    assert result["Y"].playoff_value == pytest.approx(1.0, abs=1e-6)
    assert result["Z"].playoff_value == pytest.approx(-1.0, abs=1e-6)


def test_playoff_window_values_matches_playoff_values_default_window_identically() -> None:
    # playoff_values must be built ON TOP of playoff_window_values (not a
    # parallel copy) -- same profiles in, byte-identical expected_games/z out
    settings = _settings()
    values = {
        "A": _player_value(per_game_value=5.0, availability_adjusted_value=5.0),
        "B": _player_value(per_game_value=3.0, availability_adjusted_value=1.0),
        "C": _player_value(per_game_value=0.0, availability_adjusted_value=0.0),
    }
    availabilities = {pid: _availability(1.0) for pid in values}
    profiles = {"A": _profile(12), "B": _profile(9), "C": _profile(3)}

    combined = playoff_values(values, availabilities, profiles, settings)
    window = playoff_window_values(values, availabilities, profiles)

    for pid in values:
        assert combined[pid].expected_playoff_games == window[pid].expected_playoff_games
        assert combined[pid].playoff_value == window[pid].playoff_value_z


def test_playoff_window_values_all_unavailable_yields_all_none() -> None:
    settings = _settings()
    values = {
        "A": _player_value(per_game_value=5.0, availability_adjusted_value=5.0),
        "B": _player_value(per_game_value=3.0, availability_adjusted_value=1.0),
    }
    availabilities = {pid: _availability(1.0) for pid in values}
    profiles = {pid: UnavailableProfile() for pid in values}

    result = playoff_window_values(values, availabilities, profiles)

    for pid in values:
        assert result[pid].expected_playoff_games is None
        assert result[pid].playoff_value_z is None


def test_playoff_window_values_player_missing_profile_individually_none() -> None:
    values = {
        "X": _player_value(per_game_value=1.0, availability_adjusted_value=1.0),
        "Y": _player_value(per_game_value=2.0, availability_adjusted_value=2.0),
    }
    availabilities = {"Y": _availability(1.0)}  # X deliberately has no availability entry
    profiles = {"Y": _profile(10)}  # X missing entirely

    result = playoff_window_values(values, availabilities, profiles)

    assert result["X"].expected_playoff_games is None
    assert result["X"].playoff_value_z is None
    # single-player population z is always 0.0 (zero variance)
    assert result["Y"].playoff_value_z == pytest.approx(0.0)


def test_zero_variance_pool_yields_all_zeros() -> None:
    settings = _settings()
    values = {
        "A": _player_value(per_game_value=4.0, availability_adjusted_value=2.0),
        "B": _player_value(per_game_value=4.0, availability_adjusted_value=2.0),
        "C": _player_value(per_game_value=4.0, availability_adjusted_value=2.0),
    }
    availabilities = {pid: _availability(1.0) for pid in values}
    profiles = {pid: _profile(10) for pid in values}

    result = playoff_values(values, availabilities, profiles, settings)

    for pid in values:
        assert result[pid].regular_season_z == 0.0
        assert result[pid].playoff_value == 0.0
        assert result[pid].combined_value == 0.0
