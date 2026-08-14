"""Tests for the games-played and injury-risk model (nineproj.models.availability)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from nineproj.config import Settings, load_settings
from nineproj.data.nba_stats import SeasonLine
from nineproj.models.availability import project_availability
from nineproj.research.schema import InjuryNote, SourceRef

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


@pytest.fixture()
def settings() -> Settings:
    return load_settings(SHIPPED_SETTINGS)


def _season_line(season: str, games: int, age: float = 26.0) -> SeasonLine:
    # only `games` (and occasionally `age`) vary across these tests; the rest
    # of the per-game line is irrelevant to availability math, so it's zeroed
    return SeasonLine(
        season=season,
        player_id=1,
        name="Test Player",
        team="TST",
        position="F",
        age=age,
        games=games,
        minutes=30.0,
        fgm=0.0,
        fga=0.0,
        ftm=0.0,
        fta=0.0,
        tpm=0.0,
        pts=0.0,
        reb=0.0,
        ast=0.0,
        stl=0.0,
        blk=0.0,
        tov=0.0,
    )


def _source() -> SourceRef:
    return SourceRef(
        source="Test Wire",
        url="https://example.com/wire/x",
        retrieved="2026-08-01",
        season_label="2026-27",
        quality_tier="high",
        type="news",
    )


def _injury_note(
    games_impact_estimate: int | None = None, chronic: bool = False
) -> InjuryNote:
    return InjuryNote(
        player="Test Player",
        status="questionable",
        games_impact_estimate=games_impact_estimate,
        chronic=chronic,
        source=_source(),
        note=None,
    )


def test_iron_man_gets_low_risk_and_adjusted_near_raw(settings: Settings) -> None:
    # 80/79/81 GP across three seasons, no evidence of any injury -> the
    # model should barely shrink games at all
    history = {
        "2025-26": _season_line("2025-26", 80, age=26),
        "2024-25": _season_line("2024-25", 79, age=25),
        "2023-24": _season_line("2023-24", 81, age=24),
    }
    result = project_availability(26, history, [], settings)

    assert result.injury_risk_label == "low"
    assert abs(result.raw_projected_games - result.injury_adjusted_games) <= 2


def test_declining_games_played_raises_risk_above_low(settings: Settings) -> None:
    # 40/45/50 GP (declining toward the most recent season), age 30 -- a
    # meaningfully worse availability profile than the iron man case above
    history = {
        "2025-26": _season_line("2025-26", 40, age=30),
        "2024-25": _season_line("2024-25", 45, age=29),
        "2023-24": _season_line("2023-24", 50, age=28),
    }
    result = project_availability(30, history, [], settings)

    assert result.injury_risk_label != "low"
    assert result.injury_risk_score >= settings.availability.risk_thresholds.low
    assert result.injury_adjusted_games < 76
    assert result.injury_adjusted_games < result.raw_projected_games


def test_current_injury_ceiling_overrides_healthy_history(settings: Settings) -> None:
    # healthy 75/78/74 GP history, but a source reports 35 games missed right
    # now -- the reported absence must govern, not the historical blend
    history = {
        "2025-26": _season_line("2025-26", 75, age=26),
        "2024-25": _season_line("2024-25", 78, age=25),
        "2023-24": _season_line("2023-24", 74, age=24),
    }
    notes = [_injury_note(games_impact_estimate=35, chronic=False)]
    result = project_availability(26, history, notes, settings)

    assert result.raw_projected_games > 70  # history alone reads as healthy
    assert result.injury_adjusted_games <= 82 - 35
    assert result.injury_adjusted_games == 47


def test_chronic_flag_raises_risk_versus_identical_player_without_it(
    settings: Settings,
) -> None:
    history = {
        "2025-26": _season_line("2025-26", 80, age=26),
        "2024-25": _season_line("2024-25", 79, age=25),
        "2023-24": _season_line("2023-24", 81, age=24),
    }
    healthy = project_availability(26, history, [], settings)
    with_chronic = project_availability(26, history, [_injury_note(chronic=True)], settings)

    assert with_chronic.injury_risk_score > healthy.injury_risk_score
    assert with_chronic.injury_risk_score - healthy.injury_risk_score == pytest.approx(
        settings.availability.chronic_penalty
    )


def test_bounds_hold_and_empty_history_regresses_to_league_median(
    settings: Settings,
) -> None:
    result = project_availability(25, {}, [], settings)

    assert result.raw_projected_games == settings.availability.league_median_games
    assert result.confidence <= 0.4
    assert 0 <= result.injury_adjusted_games <= 82

    # an extreme case (old, chronic, near-season-long reported absence, thin
    # recent history) still must not push adjusted games outside [0, 82]
    thin_history = {
        "2025-26": _season_line("2025-26", 2, age=40),
        "2024-25": _season_line("2024-25", 3, age=39),
        "2023-24": _season_line("2023-24", 1, age=38),
    }
    extreme = project_availability(
        40, thin_history, [_injury_note(games_impact_estimate=80, chronic=True)], settings
    )
    assert 0 <= extreme.injury_adjusted_games <= 82
    assert extreme.injury_risk_score <= 1.0


def test_missing_latest_season_zero_fills_into_blend(settings: Settings) -> None:
    # B1: a returner with 2024-25 (70gp) and 2023-24 (74gp) on record but
    # nothing for 2025-26 (season-long absence, not missing data) -- the
    # missing season counts as a real 0 at its full blend weight
    history = {
        "2024-25": _season_line("2024-25", 70, age=25),
        "2023-24": _season_line("2023-24", 74, age=24),
    }
    result = project_availability(26, history, [], settings)

    # raw = (5*0 + 3*70 + 1*74) / 9
    assert result.raw_projected_games == pytest.approx(31.555556, abs=1e-6)


def test_two_of_three_seasons_present_exact_blend_value(settings: Settings) -> None:
    # a different 2-of-3 gap shape (oldest season missing instead of newest)
    # so this is a genuinely distinct case from the zero-fill test above: no
    # evidence for 2023-24 at all (pre-debut), so it's excluded entirely --
    # weight and all -- rather than zero-filled
    history = {
        "2025-26": _season_line("2025-26", 60, age=25),
        "2024-25": _season_line("2024-25", 55, age=24),
    }
    result = project_availability(25, history, [], settings)

    # raw = (5*60 + 3*55) / (5+3) -- 2023-24's weight (1) never enters the blend
    assert result.raw_projected_games == pytest.approx((5 * 60 + 3 * 55) / 8, abs=1e-6)


def test_risk_score_matches_hand_computed_value_to_six_decimals(
    settings: Settings,
) -> None:
    # independently derive the expected risk score with exact rational
    # arithmetic (not by re-running the implementation) for the declining
    # 40/45/50 GP, age-30 case above
    weighted_sum = 5 * 40 + 3 * 45 + 1 * 50  # blend_weights [5, 3, 1]
    raw = Fraction(weighted_sum, 9)
    missed_share = 1 - raw / 82
    expected_risk = Fraction("0.6") * missed_share + Fraction("0.05")  # 28-31 age penalty

    history = {
        "2025-26": _season_line("2025-26", 40, age=30),
        "2024-25": _season_line("2024-25", 45, age=29),
        "2023-24": _season_line("2023-24", 50, age=28),
    }
    result = project_availability(30, history, [], settings)

    assert result.injury_risk_score == pytest.approx(float(expected_risk), abs=1e-6)
    assert round(result.injury_risk_score, 6) == round(float(expected_risk), 6)
