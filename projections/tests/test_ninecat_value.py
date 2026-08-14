"""Tests for nineproj.value.ninecat: 9-cat valuation, scarcity, punt values (Task 10)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from ninecat.engine.positions import slot_classes

from nineproj.config import Settings, load_settings
from nineproj.data.universe import PlayerRecord
from nineproj.models.availability import Availability
from nineproj.models.baseline import BaselineProjection
from nineproj.models.roles import AdjustedProjection, RoleChange
from nineproj.value.ninecat import CATEGORIES, category_scarcity_weights, value_pool

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


def _settings() -> Settings:
    return load_settings(SHIPPED_SETTINGS)


def _baseline() -> BaselineProjection:
    # synthetic placeholder pre_adjustment -- valuation only reads the
    # AdjustedProjection's own stat fields, never pre_adjustment's
    return BaselineProjection(
        minutes=30.0,
        games=None,
        fgm=0.0, fga=0.0, ftm=0.0, fta=0.0, tpm=0.0, pts=0.0,
        reb=0.0, ast=0.0, stl=0.0, blk=0.0, tov=0.0,
        sample_size_score=1.0,
        seasons_used=["2025-26"],
    )


def _role_change() -> RoleChange:
    return RoleChange(
        direction="neutral", score=0.0, minutes_delta=0.0, usage_delta=0.0, confidence=0.7
    )


def _projection(
    *,
    minutes: float = 30.0,
    fgm: float = 5.0,
    fga: float = 10.0,
    ftm: float = 4.0,
    fta: float = 5.0,
    tpm: float = 1.0,
    pts: float = 15.0,
    reb: float = 5.0,
    ast: float = 3.0,
    stl: float = 1.0,
    blk: float = 0.5,
    tov: float = 2.0,
) -> AdjustedProjection:
    return AdjustedProjection(
        minutes=minutes,
        fgm=fgm, fga=fga, ftm=ftm, fta=fta, tpm=tpm, pts=pts,
        reb=reb, ast=ast, stl=stl, blk=blk, tov=tov,
        pre_adjustment=_baseline(),
        role_change=_role_change(),
        pace_multiplier=1.0,
    )


def _availability(games: int) -> Availability:
    return Availability(
        raw_projected_games=float(games),
        injury_risk_score=0.1,
        injury_risk_label="low",
        injury_adjusted_games=games,
        availability_probability=games / 82,
        confidence=0.9,
    )


def _record(pid: str, position: str) -> PlayerRecord:
    # pool keys in these tests are arbitrary strings (not numeric pids), so
    # player_id is a stable hash rather than int(pid); PlayerRecord.player_id
    # is never used by value_pool (records is keyed by the pool's pid strings)
    return PlayerRecord(
        player_id=abs(hash(pid)) % 10_000,
        name=f"Player {pid}",
        team="TST",
        position=position,
        slot_classes=slot_classes(position),
        age=25.0,
        seasons_available=["2025-26"],
    )


# --- (a) per-game ordering + one hand-computed z ---------------------------


def test_per_game_value_ordering_matches_hand_computed_zscore() -> None:
    # only pts varies across the 3 players; every other stat is identical
    # (zero population variance -> z=0.0) or has zero attempts (explicit
    # zero-impact branch), so per_game_value collapses to exactly the pts z
    common = dict(fgm=5.0, fga=10.0, ftm=4.0, fta=5.0, tpm=1.0, reb=5.0, ast=3.0, stl=1.0, blk=0.5, tov=2.0)
    projections = {
        "1": _projection(pts=20.0, **common),
        "2": _projection(pts=25.0, **common),
        "3": _projection(pts=30.0, **common),
    }
    availabilities = {pid: _availability(70) for pid in projections}
    records = {pid: _record(pid, "F") for pid in projections}

    values = value_pool(projections, availabilities, records, _settings())

    assert values["3"].per_game_value > values["2"].per_game_value > values["1"].per_game_value

    # hand-computed pts z for player "3": mean=25, population std=sqrt(50/3)
    mean = (20.0 + 25.0 + 30.0) / 3
    variance = ((20.0 - mean) ** 2 + (25.0 - mean) ** 2 + (30.0 - mean) ** 2) / 3
    expected_z_3 = (30.0 - mean) / math.sqrt(variance)

    assert values["3"].per_game_zscores["pts"] == pytest.approx(expected_z_3, abs=1e-6)
    assert values["3"].per_game_value == pytest.approx(expected_z_3, abs=1e-6)
    assert values["2"].per_game_value == pytest.approx(0.0, abs=1e-9)


# --- (b) elite-but-fragile availability flip --------------------------------


def test_availability_adjusted_value_flips_elite_fragile_below_good_durable() -> None:
    # A: 25 pts/game but only 50 games; B: 20 pts/game over 75 games.
    # Per-game, A > B (25 > 20). On season totals, B's extra games overtake A:
    # 25*50=1250 vs 20*75=1500, so the availability-adjusted ordering flips.
    zero = dict(fgm=0.0, fga=0.0, ftm=0.0, fta=0.0, tpm=0.0, reb=0.0, ast=0.0, stl=0.0, blk=0.0, tov=0.0)
    projections = {
        "A": _projection(pts=25.0, **zero),
        "B": _projection(pts=20.0, **zero),
    }
    availabilities = {"A": _availability(50), "B": _availability(75)}
    records = {pid: _record(pid, "G") for pid in projections}

    values = value_pool(projections, availabilities, records, _settings())

    assert values["A"].per_game_value > values["B"].per_game_value
    assert values["A"].per_game_value == pytest.approx(1.0)
    assert values["B"].per_game_value == pytest.approx(-1.0)

    assert values["A"].availability_adjusted_value < values["B"].availability_adjusted_value
    assert values["A"].availability_adjusted_value == pytest.approx(-1.0)
    assert values["B"].availability_adjusted_value == pytest.approx(1.0)


# --- (c) punt-FT for a poor-FT big -----------------------------------------


def test_punt_ft_pct_exceeds_standard_value_for_poor_ft_shooter() -> None:
    big = _projection(
        fga=12.0, fgm=6.0, fta=8.0, ftm=3.0,  # 37.5% FT, high volume, poor
        tpm=0.0, pts=15.0, reb=11.0, ast=1.0, stl=0.5, blk=2.0, tov=2.0,
    )
    star = _projection(
        fga=15.0, fgm=8.0, fta=6.0, ftm=5.5,  # 91.7% FT
        tpm=2.0, pts=22.0, reb=5.0, ast=6.0, stl=1.5, blk=0.3, tov=3.0,
    )
    projections = {"big": big, "star": star}
    availabilities = {pid: _availability(72) for pid in projections}
    records = {pid: _record(pid, "C" if pid == "big" else "G") for pid in projections}

    values = value_pool(projections, availabilities, records, _settings())

    assert values["big"].per_game_zscores["ft_pct"] < 0
    assert values["big"].punt_values["ft_pct"] > values["big"].per_game_value


# --- (d) scarcity weighting ---------------------------------------------


def test_scarcity_weights_blocks_over_pts_when_blocks_are_scarce() -> None:
    # blocks: exactly one outlier (P1) clears z>=1; pts: three players (P2-P4)
    # clear z>=1 (P1, P5, P6 low). Everything else is identical across all
    # six players so it contributes 0 to every z (population std 0).
    flat = dict(fga=0.0, fgm=0.0, fta=0.0, ftm=0.0, tpm=1.0, reb=5.0, ast=3.0, stl=1.0, tov=2.0)
    projections = {
        "P1": _projection(pts=15.0, blk=3.5, **flat),
        "P2": _projection(pts=30.0, blk=0.3, **flat),
        "P3": _projection(pts=30.0, blk=0.3, **flat),
        "P4": _projection(pts=30.0, blk=0.3, **flat),
        "P5": _projection(pts=15.0, blk=0.3, **flat),
        "P6": _projection(pts=15.0, blk=0.3, **flat),
    }
    availabilities = {pid: _availability(65) for pid in projections}
    records = {pid: _record(pid, "F") for pid in projections}

    values = value_pool(projections, availabilities, records, _settings())

    # sanity: exactly 1 blocks outlier, exactly 3 pts outliers, as designed
    blk_high = [pid for pid, v in values.items() if v.per_game_zscores["blk"] >= 1.0]
    pts_high = [pid for pid, v in values.items() if v.per_game_zscores["pts"] >= 1.0]
    assert blk_high == ["P1"]
    assert sorted(pts_high) == ["P2", "P3", "P4"]

    weights = category_scarcity_weights(
        {pid: v.per_game_zscores for pid, v in values.items()}
    )
    assert weights["blk"] > weights["pts"]

    # the lone shot-blocker's positive blk z (weighted heavily) outweighs a
    # scorer's positive pts z (weighted lightly) in the scarcity composite
    assert values["P1"].scarcity_score > values["P2"].scarcity_score


# --- (e) zero-variance pool edge --------------------------------------------


def test_identical_pool_is_finite_and_scarcity_scores_are_zero() -> None:
    projections = {str(i): _projection() for i in range(4)}
    availabilities = {pid: _availability(70) for pid in projections}
    records = {pid: _record(pid, "F") for pid in projections}

    values = value_pool(projections, availabilities, records, _settings())

    for pid, value in values.items():
        assert math.isfinite(value.per_game_value)
        assert math.isfinite(value.availability_adjusted_value)
        assert all(math.isfinite(z) for z in value.per_game_zscores.values())
        assert value.scarcity_score == pytest.approx(0.0)
        assert all(math.isfinite(v) for v in value.punt_values.values())


# --- position_scarcity_context: above-median counts + missing-record UTIL ---


def test_position_scarcity_context_counts_above_median_and_missing_record_falls_to_util() -> None:
    common = dict(fgm=5.0, fga=10.0, ftm=4.0, fta=5.0, tpm=1.0, reb=5.0, ast=3.0, stl=1.0, blk=0.5, tov=2.0)
    projections = {
        "low": _projection(pts=10.0, **common),
        "mid": _projection(pts=15.0, **common),
        "high_g": _projection(pts=20.0, **common),
        "high_no_record": _projection(pts=25.0, **common),
    }
    availabilities = {pid: _availability(70) for pid in projections}
    # "high_no_record" deliberately has no PlayerRecord entry
    records = {
        "low": _record("low", "F"),
        "mid": _record("mid", "F"),
        "high_g": _record("high_g", "G"),
    }

    values = value_pool(projections, availabilities, records, _settings())
    context = values["low"].position_scarcity_context

    # median of [z_low, z_mid, z_high_g, z_high_no_record] leaves the two
    # highest-pts players above it: high_g (a G/PG/SG/UTIL record) and
    # high_no_record (falls back to UTIL-only since it has no record)
    assert context["UTIL"] == 2
    assert context.get("G") == 1
    assert "F" not in context or context["F"] == 0
    # shared-reference convention: same dict object on every player
    assert values["mid"].position_scarcity_context is context
