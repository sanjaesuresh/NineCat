"""Tests for nineproj.models.environment: team-pace estimate + pace adjustment (Task 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nineproj.config import Settings, load_settings
from nineproj.data.nba_stats import SeasonLine
from nineproj.models.baseline import BaselineProjection
from nineproj.models.environment import apply_environment, team_pace_estimates
from nineproj.models.roles import AdjustedProjection, RoleChange

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


def _settings() -> Settings:
    return load_settings(SHIPPED_SETTINGS)


def _line(
    team: str,
    player_id: int,
    games: int,
    fga: float,
    fta: float,
    tov: float,
) -> SeasonLine:
    return SeasonLine(
        season="2025-26",
        player_id=player_id,
        name=f"Player {player_id}",
        team=team,
        position="Guard",
        age=27.0,
        games=games,
        minutes=30.0,
        fgm=0.0,
        fga=fga,
        ftm=0.0,
        fta=fta,
        tpm=0.0,
        pts=0.0,
        reb=0.0,
        ast=0.0,
        stl=0.0,
        blk=0.0,
        tov=tov,
    )


def _adjusted(
    fgm: float = 6.0,
    fga: float = 12.0,
    ftm: float = 3.0,
    fta: float = 4.0,
    tpm: float = 2.0,
    pts: float = 17.0,
    reb: float = 5.0,
    ast: float = 4.0,
    stl: float = 1.0,
    blk: float = 0.5,
    tov: float = 2.0,
) -> AdjustedProjection:
    role_change = RoleChange(
        direction="neutral", score=0.0, minutes_delta=0.0, usage_delta=0.0, confidence=0.7
    )
    baseline = BaselineProjection(
        minutes=30.0,
        games=None,
        fgm=fgm,
        fga=fga,
        ftm=ftm,
        fta=fta,
        tpm=tpm,
        pts=pts,
        reb=reb,
        ast=ast,
        stl=stl,
        blk=blk,
        tov=tov,
        sample_size_score=1.0,
        seasons_used=["2025-26"],
    )
    return AdjustedProjection(
        minutes=30.0,
        fgm=fgm,
        fga=fga,
        ftm=ftm,
        fta=fta,
        tpm=tpm,
        pts=pts,
        reb=reb,
        ast=ast,
        stl=stl,
        blk=blk,
        tov=tov,
        pre_adjustment=baseline,
        role_change=role_change,
        pace_multiplier=1.0,
    )


# ---------------------------------------------------------------------------
# team_pace_estimates
# ---------------------------------------------------------------------------


def test_team_pace_estimates_hand_built_two_team_lines() -> None:
    lines = [
        _line("ATL", player_id=1, games=70, fga=15.0, fta=5.0, tov=3.0),
        _line("ATL", player_id=2, games=82, fga=10.0, fta=2.0, tov=1.0),
        _line("BOS", player_id=3, games=60, fga=8.0, fta=3.0, tov=2.0),
    ]
    estimates = team_pace_estimates(lines)

    # (fga + 0.44*fta + tov) * games, summed per team, divided by that team's max games
    atl_sum = (15.0 + 0.44 * 5.0 + 3.0) * 70 + (10.0 + 0.44 * 2.0 + 1.0) * 82
    bos_sum = (8.0 + 0.44 * 3.0 + 2.0) * 60
    assert estimates["ATL"] == pytest.approx(atl_sum / 82)
    assert estimates["BOS"] == pytest.approx(bos_sum / 60)


def test_team_pace_estimates_omits_teams_with_no_lines() -> None:
    lines = [_line("ATL", player_id=1, games=70, fga=15.0, fta=5.0, tov=3.0)]
    estimates = team_pace_estimates(lines)
    assert set(estimates) == {"ATL"}


# ---------------------------------------------------------------------------
# apply_environment
# ---------------------------------------------------------------------------


def test_pace_ratio_capped_at_positive_5_percent() -> None:
    settings = _settings()
    adjusted = _adjusted(pts=17.0, fga=12.0)
    result = apply_environment(adjusted, old_pace=100.0, new_pace=112.0, settings=settings)  # ratio 1.12

    assert result.pace_multiplier == pytest.approx(1.05)
    assert result.pts == pytest.approx(17.0 * 1.05)
    assert result.fga == pytest.approx(12.0 * 1.05)


def test_pace_ratio_floored_at_negative_5_percent() -> None:
    settings = _settings()
    adjusted = _adjusted(pts=17.0)
    result = apply_environment(adjusted, old_pace=100.0, new_pace=90.0, settings=settings)  # ratio 0.9

    assert result.pace_multiplier == pytest.approx(0.95)
    assert result.pts == pytest.approx(17.0 * 0.95)


def test_none_pace_leaves_projection_unchanged() -> None:
    settings = _settings()
    adjusted = _adjusted(pts=17.0)

    result_no_old = apply_environment(adjusted, old_pace=None, new_pace=105.0, settings=settings)
    assert result_no_old.pace_multiplier == 1.0
    assert result_no_old.pts == pytest.approx(17.0)

    result_no_new = apply_environment(adjusted, old_pace=100.0, new_pace=None, settings=settings)
    assert result_no_new.pace_multiplier == 1.0
    assert result_no_new.pts == pytest.approx(17.0)

    result_zero_old = apply_environment(adjusted, old_pace=0.0, new_pace=105.0, settings=settings)
    assert result_zero_old.pace_multiplier == 1.0
    assert result_zero_old.pts == pytest.approx(17.0)

    result_zero_new = apply_environment(adjusted, old_pace=100.0, new_pace=0.0, settings=settings)
    assert result_zero_new.pace_multiplier == 1.0
    assert result_zero_new.pts == pytest.approx(17.0)
