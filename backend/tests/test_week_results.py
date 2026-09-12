# Hand-built stub client returning already-parsed dataclasses (LeagueInfo,
# TeamInfo, LeagueSettings, Matchup/MatchupTeam) rather than raw JSON --
# mirrors test_league_sync.py's _StubClient convention. The JSON-fixture
# layer (tests/fixtures/yahoo/) already covers scoreboard/roster parsing
# (test_yahoo_client.py, test_yahoo_parsers.py); this module sits one layer
# above the parser, same as sync/league_sync.py's own tests.
from datetime import date, timedelta

from sqlalchemy import select

from ninecat.models.core import FantasyWeek, League, Team, WeekResult
from ninecat.sync.week_results import SkippedWeek, backfill_week_results
from ninecat.warehouse.fantasy_weeks import DATE_SOURCE_YAHOO, derive_week_range
from ninecat.yahoo.parsers import (
    CategoryInfo,
    LeagueInfo,
    LeagueSettings,
    Matchup,
    MatchupTeam,
    RosterPosition,
    TeamInfo,
)

LEAGUE_KEY = "466.l.5001"
TEAM_A_KEY = f"{LEAGUE_KEY}.t.1"
TEAM_B_KEY = f"{LEAGUE_KEY}.t.2"

# FG%, FT%, 3PTM, PTS, REB, AST, ST, BLK, TO -- yahoo's real stat_ids for a
# standard 9-cat NBA league (pinned by the live-recorded league_settings.json
# fixture: test_get_league_settings_parses_nine_categories... asserts the
# same {5,8,10,12,15,16,17,18,19} set)
_STAT_IDS = {"FG%": 5, "FT%": 8, "3PTM": 10, "PTS": 12, "REB": 15, "AST": 16, "ST": 17, "BLK": 18, "TO": 19}


class _StubClient:
    def __init__(self, scoreboard_by_week: dict[int, list[Matchup]]):
        self._scoreboard_by_week = scoreboard_by_week

    def get_league_info(self, league_key: str) -> LeagueInfo:
        return LeagueInfo(
            league_key=league_key, name="Historical League", season="2025",
            scoring_type="head", num_teams=2,
        )

    def get_league_settings(self, league_key: str) -> LeagueSettings:
        categories = [
            CategoryInfo(stat_id=stat_id, name=name, display_name=name, is_negative=(name == "TO"))
            for name, stat_id in _STAT_IDS.items()
        ]
        return LeagueSettings(
            categories=categories,
            roster_positions=[RosterPosition(position="PG", count=1)],
            max_weekly_adds=4,
            playoff_start_week=20,
            num_playoff_teams=4,
        )

    def get_league_teams(self, league_key: str) -> list[TeamInfo]:
        return [
            TeamInfo(team_key=TEAM_A_KEY, name="Team A", logo_url=None, manager_name=None),
            TeamInfo(team_key=TEAM_B_KEY, name="Team B", logo_url=None, manager_name=None),
        ]

    def get_scoreboard(self, league_key: str, week: int | None = None) -> list[Matchup]:
        return self._scoreboard_by_week.get(week, [])


def _totals(fg, ft, tpm, pts, reb, ast, stl, blk, tov) -> dict[int, str]:
    values = {"FG%": fg, "FT%": ft, "3PTM": tpm, "PTS": pts, "REB": reb, "AST": ast, "ST": stl, "BLK": blk, "TO": tov}
    return {_STAT_IDS[name]: value for name, value in values.items()}


def _week_result(db_session, team_id: int, week: int) -> WeekResult:
    return db_session.execute(
        select(WeekResult).where(WeekResult.team_id == team_id, WeekResult.week == week)
    ).scalar_one()


def _teams(db_session) -> tuple[Team, Team]:
    league = db_session.execute(
        select(League).where(League.yahoo_league_key == LEAGUE_KEY)
    ).scalar_one()
    team_a = db_session.execute(
        select(Team).where(Team.league_id == league.id, Team.yahoo_team_key == TEAM_A_KEY)
    ).scalar_one()
    team_b = db_session.execute(
        select(Team).where(Team.league_id == league.id, Team.yahoo_team_key == TEAM_B_KEY)
    ).scalar_one()
    return team_a, team_b


# team A wins 5 categories (FG%, FT%, 3PTM, AST, ST), team B wins 4 (PTS,
# REB, BLK, and TO -- A's raw 40 turnovers is MORE than B's 35, so B must
# win TO once the negative-category inversion is applied); 5-4 overall
_MATCHUP_TEAM_A = MatchupTeam(
    team_key=TEAM_A_KEY, name="Team A",
    category_totals=_totals(".500", ".800", "10", "300", "100", "60", "20", "10", "40"),
)
_MATCHUP_TEAM_B = MatchupTeam(
    team_key=TEAM_B_KEY, name="Team B",
    category_totals=_totals(".450", ".750", "8", "310", "110", "55", "18", "12", "35"),
)


def test_backfill_writes_completed_week_and_counts_categories_respecting_tov_inversion(db_session):
    matchup = Matchup(
        week=1, teams=[_MATCHUP_TEAM_A, _MATCHUP_TEAM_B],
        week_start=date(2025, 11, 3), week_end=date(2025, 11, 9),
    )
    client = _StubClient({1: [matchup], 2: []})

    report = backfill_week_results(db_session, client, LEAGUE_KEY)

    assert report.weeks_written == [1]
    assert report.rows_upserted == 2
    assert [s.week for s in report.weeks_skipped] == [2]
    assert report.weeks_skipped[0].reason == "no_matchups"

    team_a, team_b = _teams(db_session)
    result_a = _week_result(db_session, team_a.id, 1)
    result_b = _week_result(db_session, team_b.id, 1)

    # 5-4: A wins the majority of categories (including TO, correctly
    # inverted) despite fewer raw counting totals in PTS/REB/BLK
    assert result_a.result == "win"
    assert result_b.result == "loss"
    assert result_a.category_totals == {
        "fg_pct": 0.5, "ft_pct": 0.8, "tpm": 10.0, "pts": 300.0, "reb": 100.0,
        "ast": 60.0, "stl": 20.0, "blk": 10.0, "tov": 40.0,
    }


def test_backfill_skips_week_with_empty_totals_and_stops_walk(db_session):
    incomplete_b = MatchupTeam(
        team_key=TEAM_B_KEY, name="Team B",
        category_totals=_totals(".450", ".750", "8", "", "110", "55", "18", "12", "35"),
    )
    matchup = Matchup(
        week=1, teams=[_MATCHUP_TEAM_A, incomplete_b],
        week_start=date(2025, 11, 3), week_end=date(2025, 11, 9),
    )
    client = _StubClient({1: [matchup]})

    report = backfill_week_results(db_session, client, LEAGUE_KEY)

    assert report.weeks_written == []
    assert report.rows_upserted == 0
    assert report.weeks_skipped == [SkippedWeek(week=1, reason="empty_totals")]
    assert db_session.execute(select(WeekResult)).scalars().all() == []


def test_backfill_skips_future_week_but_still_resolves_its_dates(db_session):
    future_matchup = Matchup(
        week=1, teams=[_MATCHUP_TEAM_A, _MATCHUP_TEAM_B],
        week_start=date(2099, 1, 5), week_end=date(2099, 1, 11),
    )
    client = _StubClient({1: [future_matchup]})

    report = backfill_week_results(db_session, client, LEAGUE_KEY)

    assert report.weeks_written == []
    assert report.weeks_skipped[0].reason == "future_end_date"
    assert db_session.execute(select(WeekResult)).scalars().all() == []

    # resolve_week still ran (the "free by-product" applies even to a week
    # this backfill declines to write a result for)
    league = db_session.execute(select(League).where(League.yahoo_league_key == LEAGUE_KEY)).scalar_one()
    fantasy_week = db_session.execute(
        select(FantasyWeek).where(FantasyWeek.league_id == league.id, FantasyWeek.week == 1)
    ).scalar_one()
    assert fantasy_week.start_date == date(2099, 1, 5)
    assert fantasy_week.date_source == DATE_SOURCE_YAHOO


def test_backfill_with_explicit_through_week_does_not_stop_at_a_skipped_week(db_session):
    week_1 = Matchup(
        week=1, teams=[_MATCHUP_TEAM_A, _MATCHUP_TEAM_B],
        week_start=date(2025, 11, 3), week_end=date(2025, 11, 9),
    )
    incomplete_week_2_b = MatchupTeam(
        team_key=TEAM_B_KEY, name="Team B",
        category_totals=_totals(".450", ".750", "8", "", "110", "55", "18", "12", "35"),
    )
    week_2 = Matchup(
        week=2, teams=[_MATCHUP_TEAM_A, incomplete_week_2_b],
        week_start=date(2025, 11, 10), week_end=date(2025, 11, 16),
    )
    week_3 = Matchup(
        week=3, teams=[_MATCHUP_TEAM_A, _MATCHUP_TEAM_B],
        week_start=date(2025, 11, 17), week_end=date(2025, 11, 23),
    )
    client = _StubClient({1: [week_1], 2: [week_2], 3: [week_3]})

    # an explicit through_week attempts every week in range regardless of an
    # earlier week's outcome, unlike the open-ended walk (through_week=None)
    # which stops at the first incomplete/future week
    report = backfill_week_results(db_session, client, LEAGUE_KEY, through_week=3)

    assert report.weeks_written == [1, 3]
    assert [s.week for s in report.weeks_skipped] == [2]
    assert report.weeks_skipped[0].reason == "empty_totals"
    assert report.rows_upserted == 4


def test_backfill_is_idempotent_on_rerun(db_session):
    matchup = Matchup(
        week=1, teams=[_MATCHUP_TEAM_A, _MATCHUP_TEAM_B],
        week_start=date(2025, 11, 3), week_end=date(2025, 11, 9),
    )
    client = _StubClient({1: [matchup], 2: []})

    first = backfill_week_results(db_session, client, LEAGUE_KEY)
    rows_after_first = db_session.execute(select(WeekResult)).scalars().all()
    second = backfill_week_results(db_session, client, LEAGUE_KEY)
    rows_after_second = db_session.execute(select(WeekResult)).scalars().all()

    assert first.rows_upserted == second.rows_upserted == 2
    assert len(rows_after_first) == len(rows_after_second) == 2
    team_a, team_b = _teams(db_session)
    assert _week_result(db_session, team_a.id, 1).result == "win"
    assert _week_result(db_session, team_b.id, 1).result == "loss"


def test_backfill_reports_yahoo_vs_derived_date_agreement(db_session):
    derived_start, derived_end = derive_week_range(1)
    disagreeing_start = derived_start + timedelta(days=3)
    disagreeing_end = derived_end + timedelta(days=3)

    matchup = Matchup(
        week=1, teams=[_MATCHUP_TEAM_A, _MATCHUP_TEAM_B],
        week_start=disagreeing_start, week_end=disagreeing_end,
    )
    client = _StubClient({1: [matchup], 2: []})

    report = backfill_week_results(db_session, client, LEAGUE_KEY)

    assert len(report.date_comparisons) == 1
    comparison = report.date_comparisons[0]
    assert comparison.week == 1
    assert comparison.yahoo_start == disagreeing_start
    assert comparison.yahoo_end == disagreeing_end
    assert comparison.derived_start == derived_start
    assert comparison.derived_end == derived_end
    assert comparison.agrees is False
