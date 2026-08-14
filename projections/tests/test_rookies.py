"""Tests for nineproj.models.rookies: rookie model (Task 9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nineproj.config import Settings, load_settings
from nineproj.models.baseline import BaselineProjection
from nineproj.models.roles import AdjustedProjection, RoleChange
from nineproj.models.rookies import RookieFlags, project_rookie
from nineproj.research.schema import RookieNote, SourceRef

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"

_FULL_BAND = {
    "fgm": 0.2,
    "fga": 0.4,
    "ftm": 0.1,
    "fta": 0.12,
    "tpm": 0.08,
    "pts": 0.6,
    "reb": 0.15,
    "ast": 0.1,
    "stl": 0.02,
    "blk": 0.01,
    "tov": 0.05,
}


def _settings() -> Settings:
    return load_settings(SHIPPED_SETTINGS)


def _source() -> SourceRef:
    return SourceRef(
        source="Test Draft Guide",
        url="https://example.com/draft/rookie",
        retrieved="2026-06-28",
        season_label="2026-27",
        quality_tier="medium_high",
        type="projection",
    )


_UNSET = object()  # distinguishes "use the default full band" from an explicit None


def _note(
    draft_pick: int | None = 3,
    minutes_range: tuple[float, float] | None = (28.0, 32.0),
    per_minute_band: dict[str, float] | None | object = _UNSET,
) -> RookieNote:
    return RookieNote(
        player="Test Rookie",
        draft_pick=draft_pick,
        team="Test Town Titans",
        position="SG",
        expected_role="Starter",
        minutes_range=minutes_range,
        comps=["Test Comp One"],
        per_minute_band=_FULL_BAND if per_minute_band is _UNSET else per_minute_band,
        source=_source(),
    )


def test_top3_pick_narrow_range_projects_midpoint_minutes_and_high_confidence() -> None:
    note = _note(draft_pick=3, minutes_range=(28.0, 32.0))
    result = project_rookie(note, _settings())
    assert result is not None
    adjusted, flags = result

    assert adjusted.minutes == pytest.approx(30.0)
    assert adjusted.pts == pytest.approx(_FULL_BAND["pts"] * 30.0)
    assert adjusted.reb == pytest.approx(_FULL_BAND["reb"] * 30.0)
    # top-5 pick bonus (0.15) + narrow-range bonus (0.1) on top of the 0.3 base
    assert flags.projection_confidence == pytest.approx(0.55)
    # width 4 / 12 = 0.333..., above the 0.3 floor so unclamped
    assert flags.role_uncertainty == pytest.approx(4.0 / 12.0)


def test_missing_minutes_range_excluded() -> None:
    note = _note(minutes_range=None)
    assert project_rookie(note, _settings()) is None


def test_missing_band_excluded() -> None:
    note = _note(per_minute_band=None)
    assert project_rookie(note, _settings()) is None


def test_partial_band_missing_a_stat_excluded() -> None:
    partial = dict(_FULL_BAND)
    del partial["stl"]
    note = _note(per_minute_band=partial)
    assert project_rookie(note, _settings()) is None


def test_fgm_clamped_to_fga_when_band_implies_more_makes_than_attempts() -> None:
    inconsistent_band = dict(_FULL_BAND)
    inconsistent_band["fgm"] = 0.5  # rate exceeds fga's 0.4 -- analyst rounding error
    note = _note(per_minute_band=inconsistent_band)
    result = project_rookie(note, _settings())
    assert result is not None
    adjusted, _flags = result

    assert adjusted.fgm == pytest.approx(adjusted.fga)


def test_late_first_pick_wide_range_gets_low_confidence_and_capped_uncertainty() -> None:
    note = _note(draft_pick=27, minutes_range=(12.0, 24.0))
    result = project_rookie(note, _settings())
    assert result is not None
    _adjusted, flags = result

    # no top-5 bonus, width 12 > 6 so no narrow-range bonus either -> base 0.3
    assert flags.projection_confidence == pytest.approx(0.3)
    # width 12 / 12 = 1.0, clamped down to the 0.9 ceiling
    assert flags.role_uncertainty == pytest.approx(0.9)


def test_output_is_adjusted_projection_with_synthetic_zero_sample_baseline() -> None:
    note = _note()
    result = project_rookie(note, _settings())
    assert result is not None
    adjusted, flags = result

    assert isinstance(adjusted, AdjustedProjection)
    assert isinstance(adjusted.pre_adjustment, BaselineProjection)
    assert adjusted.pre_adjustment.sample_size_score == 0.0
    assert adjusted.pre_adjustment.seasons_used == []
    assert adjusted.role_change == RoleChange(
        direction="neutral",
        score=0.0,
        minutes_delta=0.0,
        usage_delta=0.0,
        confidence=flags.projection_confidence,
    )
    assert adjusted.pace_multiplier == 1.0
    assert isinstance(flags, RookieFlags)
    assert flags.rookie is True
