"""Tests for nineproj.data.schedule: fetch normalization, fantasy weeks, playoff windows."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from nineproj.config import load_settings
from nineproj.data.schedule import (
    PlayoffProfile,
    Schedule,
    ScheduleRow,
    ScheduleUnavailable,
    UnavailableProfile,
    fantasy_weeks,
    fetch_schedule,
    league_playoff_game_counts,
    playoff_profile,
    team_week_games,
)

# league-wide playoff-window (weeks 19-21) totals, hand-counted from the same
# fixture: AAA=9 (see block below), BBB=4 (02-24, 03-01, 03-07, 03-11), CCC=5
# (02-22, 02-28, 03-04, 03-08, 03-14). min-max normalized against {4, 5, 9}:
# AAA (max) -> 1.0, BBB (min) -> 0.0, CCC -> (5-4)/(9-4) = 0.2.

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "schedule_2026_27_sample.json"

# fixture hand count for team AAA (see fixtures/schedule_2026_27_sample.json):
# week 18 (02-15..02-21): 02-17, 02-20, 02-21          -> 3 games
# week 19 (02-22..02-28): 02-22, 02-24, 02-28          -> 3 games
# week 20 (03-01..03-07): 03-01, 03-04, 03-07          -> 3 games
# week 21 (03-08..03-14): 03-08, 03-11, 03-14          -> 3 games
# week 22 (03-15..03-21): 03-15, 03-18                 -> 2 games
# window (weeks 19-21) sorted dates: 02-22, 02-24, 02-28, 03-01, 03-04, 03-07,
#   03-08, 03-11, 03-14 -> 9 games total.
# consecutive-day pairs among those: (02-28, 03-01) and (03-07, 03-08) -> 2 b2bs.
# 02-21/02-22 and 03-14/03-15 are also consecutive days but each straddles the
# window edge (one date outside weeks 19-21), so neither counts.


def _fixture_fetcher(season: str) -> list[ScheduleRow]:
    rows = json.loads(FIXTURE_PATH.read_text())
    return [ScheduleRow(**row) for row in rows]


def _empty_fetcher(season: str) -> list[ScheduleRow]:
    return []


def _raising_fetcher(season: str) -> list[ScheduleRow]:
    raise RuntimeError("network unreachable")


def test_fantasy_weeks_week1_starts_at_configured_monday() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    weeks = fantasy_weeks(settings)
    assert weeks[1] == (date(2026, 10, 19), date(2026, 10, 25))
    assert len(weeks) == 26


def test_fantasy_weeks_playoff_window_weeks() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    weeks = fantasy_weeks(settings)
    assert weeks[19] == (date(2027, 2, 22), date(2027, 2, 28))
    assert weeks[20] == (date(2027, 3, 1), date(2027, 3, 7))
    assert weeks[21] == (date(2027, 3, 8), date(2027, 3, 14))


def test_fetch_schedule_normalizes_fixture_into_per_team_dates() -> None:
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    assert isinstance(schedule, Schedule)
    assert schedule.team_game_dates["AAA"][0] == date(2027, 2, 17)
    # sorted ascending per team
    assert schedule.team_game_dates["AAA"] == sorted(schedule.team_game_dates["AAA"])
    assert len(schedule.team_game_dates["AAA"]) == 14


def test_team_week_games_hand_counted_team() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    weeks = fantasy_weeks(settings)
    counts = team_week_games(schedule, weeks)

    assert counts["AAA"][18] == 3
    assert counts["AAA"][19] == 3
    assert counts["AAA"][20] == 3
    assert counts["AAA"][21] == 3
    assert counts["AAA"][22] == 2


def test_week_boundary_sunday_vs_monday() -> None:
    # 02-28 is a Sunday and belongs to week 19; 03-01 is the following Monday
    # and belongs to week 20 -- the pair is a consecutive-day back-to-back but
    # must land in two different fantasy weeks.
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    weeks = fantasy_weeks(settings)
    assert weeks[19][1] == date(2027, 2, 28)
    assert weeks[20][0] == date(2027, 3, 1)

    counts = team_week_games(schedule, weeks)
    assert date(2027, 2, 28) in [
        d for d in schedule.team_game_dates["AAA"] if weeks[19][0] <= d <= weeks[19][1]
    ]
    assert date(2027, 3, 1) in [
        d for d in schedule.team_game_dates["AAA"] if weeks[20][0] <= d <= weeks[20][1]
    ]
    assert counts["AAA"][19] == 3
    assert counts["AAA"][20] == 3


def test_playoff_profile_hand_counted_team() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    profile = playoff_profile("AAA", schedule, settings)

    assert isinstance(profile, PlayoffProfile)
    assert profile.games_by_week == {19: 3, 20: 3, 21: 3}
    assert profile.playoff_games == 9
    assert profile.playoff_b2b_count == 2
    # AAA has the league-high playoff-window count (9 of {4, 5, 9}) -> 1.0
    assert profile.playoff_schedule_score == pytest.approx(1.0)


def test_playoff_profile_score_league_low_team() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    profile = playoff_profile("BBB", schedule, settings)

    assert profile.playoff_games == 4
    # BBB has the league-low playoff-window count (4 of {4, 5, 9}) -> 0.0
    assert profile.playoff_schedule_score == pytest.approx(0.0)


def test_playoff_profile_score_league_mid_team() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    profile = playoff_profile("CCC", schedule, settings)

    assert profile.playoff_games == 5
    # CCC sits between BBB (4) and AAA (9): (5-4)/(9-4) == 0.2
    assert profile.playoff_schedule_score == pytest.approx(0.2)


def test_playoff_profile_score_degenerate_all_equal_returns_half() -> None:
    # every team has exactly 1 playoff-window game -> zero-width range -> 0.5,
    # not a divide-by-zero and not an arbitrary tiebreak
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = Schedule(
        team_game_dates={
            "XXX": [date(2027, 2, 23)],
            "YYY": [date(2027, 2, 24)],
        }
    )
    assert playoff_profile("XXX", schedule, settings).playoff_schedule_score == pytest.approx(0.5)
    assert playoff_profile("YYY", schedule, settings).playoff_schedule_score == pytest.approx(0.5)


def test_playoff_profile_excludes_edge_straddling_back_to_backs() -> None:
    # 02-21/02-22 straddles the window's start edge and 03-14/03-15 straddles
    # its end edge; both are consecutive calendar dates but only one side of
    # each pair is inside the window, so neither should inflate the b2b count
    # beyond the 2 that are fully inside (asserted above).
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    profile = playoff_profile("AAA", schedule, settings)
    assert profile.playoff_b2b_count == 2


def test_playoff_profile_window_override_18_20_hand_counted() -> None:
    # window override (dashboard dropdown), not settings.playoff_window: AAA's
    # per-week counts (see fixture hand count above) are wk18=3, wk19=3,
    # wk20=3 -> 9 games; league totals for 18-20 are AAA=9, BBB=2+1+2=5,
    # CCC=1+2+1=4, so AAA (max) normalizes to 1.0
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    profile = playoff_profile("AAA", schedule, settings, window=(18, 20))

    assert profile.games_by_week == {18: 3, 19: 3, 20: 3}
    assert profile.playoff_games == 9
    assert profile.playoff_schedule_score == pytest.approx(1.0)


def test_playoff_profile_window_override_20_22_hand_counted() -> None:
    # wk20=3, wk21=3, wk22=2 -> 8 games; league totals for 20-22 are
    # AAA=8, BBB=2+1+1=4, CCC=1+2+1=4 -> AAA is still the league max -> 1.0
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    profile = playoff_profile("AAA", schedule, settings, window=(20, 22))

    assert profile.games_by_week == {20: 3, 21: 3, 22: 2}
    assert profile.playoff_games == 8
    assert profile.playoff_schedule_score == pytest.approx(1.0)


def test_playoff_profile_window_override_defaults_to_settings_playoff_window() -> None:
    # omitting `window` must reproduce exactly the settings.playoff_window
    # (19-21) result -- back-compat for every existing caller
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    default_profile = playoff_profile("AAA", schedule, settings)
    explicit_profile = playoff_profile("AAA", schedule, settings, window=(19, 21))

    assert default_profile == explicit_profile


def test_league_playoff_game_counts_window_override() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    counts = league_playoff_game_counts(schedule, settings, window=(18, 20))
    assert counts["AAA"] == 9
    assert counts["BBB"] == 5
    assert counts["CCC"] == 4


def test_league_playoff_game_counts_matches_per_team_profile() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    schedule = fetch_schedule("2026-27", fetcher=_fixture_fetcher)
    counts = league_playoff_game_counts(schedule, settings)
    assert counts["AAA"] == 9


def test_fetch_schedule_empty_returns_unavailable() -> None:
    result = fetch_schedule("2026-27", fetcher=_empty_fetcher)
    assert isinstance(result, ScheduleUnavailable)


def test_fetch_schedule_raising_fetcher_returns_unavailable() -> None:
    result = fetch_schedule("2026-27", fetcher=_raising_fetcher)
    assert isinstance(result, ScheduleUnavailable)


def test_unavailable_schedule_yields_all_none_playoff_profile() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    unavailable = fetch_schedule("2026-27", fetcher=_empty_fetcher)
    profile = playoff_profile("AAA", unavailable, settings)

    assert isinstance(profile, UnavailableProfile)
    assert profile.games_by_week is None
    assert profile.playoff_games is None
    assert profile.playoff_b2b_count is None
    assert profile.playoff_schedule_score is None


def test_unavailable_schedule_yields_empty_team_week_games() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    unavailable = fetch_schedule("2026-27", fetcher=_empty_fetcher)
    weeks = fantasy_weeks(settings)
    assert team_week_games(unavailable, weeks) == {}


def test_unavailable_schedule_yields_empty_league_playoff_game_counts() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    unavailable = fetch_schedule("2026-27", fetcher=_empty_fetcher)
    assert league_playoff_game_counts(unavailable, settings) == {}
