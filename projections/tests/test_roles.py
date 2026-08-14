"""Tests for nineproj.models.roles: role/team-change adjustment (Task 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nineproj.config import Settings, load_settings
from nineproj.models.baseline import BaselineProjection
from nineproj.models.roles import RoleChange, apply_role_adjustment
from nineproj.research.schema import RoleNote, SourceRef

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


def _settings() -> Settings:
    return load_settings(SHIPPED_SETTINGS)


def _source(quality_tier: str = "high") -> SourceRef:
    return SourceRef(
        source="Test Wire",
        url="https://example.com/wire/x",
        retrieved="2026-08-01",
        season_label="2026-27",
        quality_tier=quality_tier,
        type="news",
    )


def _note(
    minutes_delta: float,
    usage_delta: float = 0.0,
    confidence: float = 1.0,
    weight: float | None = 1.0,
    direction: str = "positive",
) -> RoleNote:
    return RoleNote(
        player="Test Star",
        direction=direction,
        minutes_delta=minutes_delta,
        usage_delta=usage_delta,
        confidence=confidence,
        rationale="test rationale",
        source=_source(),
        weight=weight,
    )


def _baseline(
    minutes: float = 30.0,
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
) -> BaselineProjection:
    return BaselineProjection(
        minutes=minutes,
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


def test_single_minutes_note_scales_minutes_and_pts_keeps_fg_pct() -> None:
    baseline = _baseline(minutes=30.0, fgm=6.0, fga=12.0, pts=17.0)
    note = _note(minutes_delta=6.0)
    adjusted = apply_role_adjustment(baseline, [note], _settings())

    assert adjusted.minutes == pytest.approx(36.0)
    assert adjusted.pts == pytest.approx(17.0 * 1.2)
    baseline_fg_pct = baseline.fgm / baseline.fga
    adjusted_fg_pct = adjusted.fgm / adjusted.fga
    assert adjusted_fg_pct == pytest.approx(baseline_fg_pct, abs=1e-9)
    assert adjusted.role_change.minutes_delta == pytest.approx(6.0)
    # score = 0.5*(6.0/8.0) + 0.5*(0.0/5.0) = 0.375; well above the 0.05 direction threshold
    assert adjusted.role_change.score == pytest.approx(0.375)
    assert adjusted.role_change.direction == "positive"


def test_minutes_delta_capped_at_settings_cap() -> None:
    settings = _settings()
    baseline = _baseline(minutes=30.0)
    note = _note(minutes_delta=12.0)
    adjusted = apply_role_adjustment(baseline, [note], settings)

    assert adjusted.role_change.minutes_delta == pytest.approx(settings.adjustment_caps.minutes_delta)
    assert adjusted.minutes == pytest.approx(30.0 + settings.adjustment_caps.minutes_delta)


def test_conflicting_notes_average_weighted_by_quality_tier_and_penalize_confidence() -> None:
    # quality_tier_weights: high=0.85, low=0.15 (config.py); per-note weight =
    # tier_weight * confidence, exactly matching apply_role_adjustment's combine step
    high_tier_note = _note(minutes_delta=4.0, confidence=0.6, weight=0.85, direction="positive")
    low_tier_note = _note(minutes_delta=-2.0, confidence=0.5, weight=0.15, direction="negative")
    baseline = _baseline(minutes=30.0)
    adjusted = apply_role_adjustment(baseline, [high_tier_note, low_tier_note], _settings())

    w1 = 0.85 * 0.6
    w2 = 0.15 * 0.5
    expected_minutes_delta = (w1 * 4.0 + w2 * -2.0) / (w1 + w2)
    expected_confidence_pre_penalty = (w1 * 0.6 + w2 * 0.5) / (w1 + w2)
    expected_confidence = expected_confidence_pre_penalty * 0.7  # sign conflict penalty

    assert adjusted.role_change.minutes_delta == pytest.approx(expected_minutes_delta)
    assert adjusted.role_change.minutes_delta > 0
    assert adjusted.role_change.confidence == pytest.approx(expected_confidence)


def test_usage_delta_scales_creation_stats_leaves_reb_and_fg_pct_alone() -> None:
    baseline = _baseline(fga=20.0, pts=25.0, tov=3.0, reb=8.0, fgm=10.0)
    note = _note(minutes_delta=0.0, usage_delta=2.5)
    adjusted = apply_role_adjustment(baseline, [note], _settings())

    factor = 1 + 2.5 / 25.0  # exactly 1.1
    assert adjusted.fga == pytest.approx(20.0 * factor)
    assert adjusted.pts == pytest.approx(25.0 * factor)
    assert adjusted.tov == pytest.approx(3.0 * factor)
    assert adjusted.reb == pytest.approx(8.0)  # untouched by usage
    baseline_fg_pct = baseline.fgm / baseline.fga
    adjusted_fg_pct = adjusted.fgm / adjusted.fga
    assert adjusted_fg_pct == pytest.approx(baseline_fg_pct, abs=1e-9)


def test_no_notes_returns_unchanged_stats_with_neutral_zero_score() -> None:
    baseline = _baseline()
    adjusted = apply_role_adjustment(baseline, [], _settings())

    assert adjusted.minutes == baseline.minutes
    assert adjusted.pts == baseline.pts
    assert adjusted.fgm == baseline.fgm
    assert adjusted.reb == baseline.reb
    assert adjusted.role_change == RoleChange(
        direction="neutral", score=0.0, minutes_delta=0.0, usage_delta=0.0, confidence=0.7
    )
    assert adjusted.pace_multiplier == 1.0
    assert adjusted.pre_adjustment is baseline
