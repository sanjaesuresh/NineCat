"""Tests for nineproj.models.baseline: population context + Marcel-style baseline projection."""

from __future__ import annotations

from pathlib import Path

import pytest

from nineproj.config import Settings, load_settings
from nineproj.data.nba_stats import SeasonLine
from nineproj.data.universe import PlayerRecord
from nineproj.models.baseline import (
    PopulationContext,
    build_population_context,
    project_baseline,
)

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


def _settings() -> Settings:
    return load_settings(SHIPPED_SETTINGS)


def _line(
    season: str,
    player_id: int = 1,
    position: str | None = "Guard",
    age: float = 27.0,
    games: int = 80,
    minutes: float = 33.0,
    fgm: float = 7.0,
    fga: float = 15.0,
    ftm: float = 3.0,
    fta: float = 3.5,
    tpm: float = 2.0,
    pts: float = 19.0,
    reb: float = 4.5,
    ast: float = 6.0,
    stl: float = 1.2,
    blk: float = 0.3,
    tov: float = 2.5,
) -> SeasonLine:
    return SeasonLine(
        season=season,
        player_id=player_id,
        name=f"Player {player_id}",
        team="ATL",
        position=position,
        age=age,
        games=games,
        minutes=minutes,
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
    )


def _player(position: str | None = "Guard", age: float = 27.0) -> PlayerRecord:
    return PlayerRecord(
        player_id=1,
        name="Player 1",
        team="ATL",
        position=position,
        slot_classes=frozenset({"PG", "SG", "G", "UTIL"}),
        age=age,
        seasons_available=["2025-26"],
    )


_STAT_FIELDS = ("fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov")


def _empty_context() -> PopulationContext:
    # all-zero group means; only safe when shrink is 0, since final_rate still
    # reads group_mean[stat] even when multiplied by a zero shrink weight
    return PopulationContext(
        group_rates={g: dict.fromkeys(_STAT_FIELDS, 0.0) for g in ("guard", "forward", "center", "all")}
    )


# ---------------------------------------------------------------------------
# build_population_context
# ---------------------------------------------------------------------------


def test_build_population_context_weights_by_games_times_minutes_per_group() -> None:
    # two guards in the latest season: 40 games/20 min (weight 800) and 80
    # games/40 min (weight 3200) -- the second should dominate the guard mean
    lines_by_season = {
        "2025-26": [
            _line("2025-26", player_id=1, position="Guard", games=40, minutes=20.0, pts=10.0),
            _line("2025-26", player_id=2, position="Guard", games=80, minutes=40.0, pts=30.0),
            _line("2025-26", player_id=3, position="Forward", games=80, minutes=30.0, pts=15.0),
        ]
    }
    context = build_population_context(lines_by_season, _settings())

    # pts/min: player1 = 10/20 = 0.5 (weight 800), player2 = 30/40 = 0.75 (weight 3200)
    expected_guard_pts_rate = (800 * 0.5 + 3200 * 0.75) / (800 + 3200)
    assert context.group_rates["guard"]["pts"] == expected_guard_pts_rate

    # forward group only has the one line -- its rate equals that line's own rate
    assert context.group_rates["forward"]["pts"] == 15.0 / 30.0

    # "all" mixes every group's weight together
    expected_all_pts_rate = (800 * 0.5 + 3200 * 0.75 + 2400 * 0.5) / (800 + 3200 + 2400)
    assert context.group_rates["all"]["pts"] == expected_all_pts_rate


def test_build_population_context_uses_latest_season_only() -> None:
    lines_by_season = {
        "2025-26": [_line("2025-26", position="Guard", pts=20.0, minutes=20.0)],
        "2024-25": [_line("2024-25", position="Guard", pts=99.0, minutes=20.0)],
    }
    context = build_population_context(lines_by_season, _settings())
    assert context.group_rates["guard"]["pts"] == 1.0  # 20.0 / 20.0, not 99.0's rate


def test_build_population_context_skips_zero_minute_lines() -> None:
    lines_by_season = {
        "2025-26": [
            _line("2025-26", player_id=1, position="Guard", minutes=0.0, games=0),
            _line("2025-26", player_id=2, position="Guard", minutes=30.0, games=80, pts=15.0),
        ]
    }
    context = build_population_context(lines_by_season, _settings())
    assert context.group_rates["guard"]["pts"] == 15.0 / 30.0


# ---------------------------------------------------------------------------
# project_baseline
# ---------------------------------------------------------------------------


def test_stable_veteran_three_near_identical_seasons_projects_within_2_percent() -> None:
    # season rates offset by a uniform +1%/-1% around the most recent season,
    # so the 5/3/1 blend lands within a hand-checkable ~0.3% of the raw rates
    history = {
        "2025-26": _line(
            "2025-26", age=27.0, games=80, minutes=33.0,
            fgm=7.0, fga=15.0, ftm=3.0, fta=3.5, tpm=2.0,
            pts=19.0, reb=4.5, ast=6.0, stl=1.2, blk=0.3, tov=2.5,
        ),
        "2024-25": _line(
            "2024-25", age=26.0, games=80, minutes=33.0,
            fgm=7.07, fga=15.15, ftm=3.03, fta=3.535, tpm=2.02,
            pts=19.19, reb=4.545, ast=6.06, stl=1.212, blk=0.303, tov=2.525,
        ),
        "2023-24": _line(
            "2023-24", age=25.0, games=80, minutes=33.0,
            fgm=6.93, fga=14.85, ftm=2.97, fta=3.465, tpm=1.98,
            pts=18.81, reb=4.455, ast=5.94, stl=1.188, blk=0.297, tov=2.475,
        ),
    }
    # full sample (3 * 80 * 33 = 7920 >> 4500) means shrink is 0, so the group
    # mean below is never actually blended in -- only needed to satisfy the API
    context = PopulationContext(
        group_rates={"guard": dict.fromkeys(_STAT_FIELDS, 0.0), "forward": {}, "center": {}, "all": {}}
    )
    player = _player(position="Guard", age=27.0)
    projection = project_baseline(player, history, context, _settings())

    assert projection is not None
    assert projection.sample_size_score == 1.0
    raw = {
        "fgm": 7.0, "fga": 15.0, "ftm": 3.0, "fta": 3.5, "tpm": 2.0,
        "pts": 19.0, "reb": 4.5, "ast": 6.0, "stl": 1.2, "blk": 0.3, "tov": 2.5,
    }
    for stat, expected in raw.items():
        projected = getattr(projection, stat)
        assert abs(projected - expected) / expected < 0.02, f"{stat}: {projected} vs {expected}"
    assert abs(projection.minutes - 33.0) < 0.01


def test_one_season_small_sample_player_is_pulled_toward_group_mean() -> None:
    # a single 400-minute-total season (well under full_sample_minutes=4500)
    settings = _settings()
    history = {
        "2025-26": _line(
            "2025-26", age=27.0, games=20, minutes=20.0,
            fgm=10.0, fga=20.0, ftm=4.0, fta=5.0, tpm=3.0,
            pts=27.0, reb=5.0, ast=6.0, stl=1.5, blk=0.5, tov=3.0,
        ),
    }
    # a low-usage bench-guard population mean, well below this player's own rate
    context = build_population_context(
        {"2025-26": [_line(
            "2025-26", player_id=99, position="Guard", age=30.0, games=82, minutes=30.0,
            fgm=2.0, fga=5.0, ftm=1.0, fta=1.3, tpm=0.7,
            pts=9.0, reb=2.0, ast=3.0, stl=0.8, blk=0.2, tov=1.5,
        )]},
        settings,
    )
    player = _player(position="Guard", age=27.0)  # age 27: no age-curve effect isolates regression
    projection = project_baseline(player, history, context, settings)

    assert projection is not None
    expected_sample_size_score = 400 / 4500
    assert projection.sample_size_score == expected_sample_size_score
    shrink = settings.baseline.regression_strength * (1 - expected_sample_size_score)
    assert shrink > 0

    raw_pts_rate = 27.0 / 20.0  # player's own blended per-minute rate
    group_pts_rate = 9.0 / 30.0  # population guard mean per-minute rate
    projected_pts_rate = projection.pts / projection.minutes
    # pulled toward the group mean, but shrink < 1 so it never fully gets there
    assert group_pts_rate < projected_pts_rate < raw_pts_rate

    # exact hand-derived value: final_rate = (1-shrink)*raw + shrink*group,
    # then x projected minutes (== 20.0, the only season); age 27 has no
    # age-curve effect so this is the untouched regressed rate x minutes
    expected_pts = ((1 - shrink) * raw_pts_rate + shrink * group_pts_rate) * 20.0
    assert projection.pts == pytest.approx(expected_pts, abs=1e-3)
    assert projection.pts == pytest.approx(22.2167, abs=1e-3)


def test_age_36_pts_projects_below_raw_blend_age_22_at_or_above() -> None:
    settings = _settings()
    # three identical full-sample seasons -> shrink is 0, so the only variable
    # between the two players below is the age-curve multiplier
    history = {
        season: _line(season, games=80, minutes=33.0, pts=20.0)
        for season in settings.prior_seasons
    }
    context = _empty_context()

    old_player = _player(position="Guard", age=36.0)
    old_projection = project_baseline(old_player, history, context, settings)
    assert old_projection is not None
    assert old_projection.pts < 20.0  # steep decline (age > 34) shrinks volume stats
    # exact multiplier: 1 - old_penalty*(34-30) - steep_penalty*(36-34) = 1 - 0.06 - 0.07 = 0.87;
    # shrink is 0 (full sample) and minutes cancel out, so pts = 20.0 * 0.87 exactly
    assert old_projection.pts == pytest.approx(20.0 * 0.87, abs=1e-6)
    assert old_projection.pts == pytest.approx(17.4, abs=1e-6)

    young_player = _player(position="Guard", age=22.0)
    young_projection = project_baseline(young_player, history, context, settings)
    assert young_projection is not None
    assert young_projection.pts >= 20.0  # below improve_until (25) boosts volume stats


def test_makes_never_exceed_attempts_under_extreme_age_multipliers() -> None:
    settings = _settings()
    history = {
        season: _line(season, games=80, minutes=33.0, fgm=7.0, fga=15.0, ftm=3.0, fta=3.5)
        for season in settings.prior_seasons
    }
    context = _empty_context()

    for extreme_age in (10.0, 60.0):  # far below improve_until / far past steep_decline_after
        player = _player(position="Guard", age=extreme_age)
        projection = project_baseline(player, history, context, settings)
        assert projection is not None
        assert projection.fgm <= projection.fga
        assert projection.ftm <= projection.fta


def test_zero_minute_season_is_skipped_without_crashing() -> None:
    settings = _settings()
    history = {
        "2025-26": _line("2025-26", minutes=0.0, games=0),  # DNP season -- must be skipped
        "2024-25": _line("2024-25", games=80, minutes=33.0, pts=19.0),
    }
    context = _empty_context()
    player = _player(position="Guard", age=27.0)
    projection = project_baseline(player, history, context, settings)

    assert projection is not None
    assert projection.seasons_used == ["2024-25"]


def test_player_with_no_usable_seasons_returns_none() -> None:
    # contract: no prior season present with minutes>0/games>0 -> None, not a
    # zeroed-out projection, so callers can distinguish "no data" from "0 pts"
    settings = _settings()
    history = {
        "2025-26": _line("2025-26", minutes=0.0, games=0),
        "2024-25": _line("2024-25", minutes=0.0, games=0),
    }
    context = _empty_context()
    player = _player(position="Guard", age=27.0)

    assert project_baseline(player, history, context, settings) is None
    assert project_baseline(player, {}, context, settings) is None
