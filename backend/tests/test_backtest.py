# Hand-built stub client + warehouse rows (no JSON fixtures, no network) --
# same convention as test_week_results.py / test_league_sync.py: this module
# sits above the yahoo parser layer, which JSON fixtures under
# tests/fixtures/yahoo/ already cover.
from datetime import date

from sqlalchemy import select

from ninecat.analysis.backtest import (
    CategoryHitRate,
    SkippedBacktestWeek,
    TeamWeekUnmapped,
    run_matchup_backtest,
)
from ninecat.models.core import League, Team, WeekResult
from ninecat.models.warehouse import NbaGame, NbaPlayer, NbaTeam, PlayerSeasonAverage
from ninecat.warehouse.fantasy_weeks import resolve_week
from ninecat.yahoo.parsers import Matchup, MatchupTeam, RosterEntry

LEAGUE_KEY = "466.l.7001"
TEAM_A_KEY = f"{LEAGUE_KEY}.t.1"
TEAM_B_KEY = f"{LEAGUE_KEY}.t.2"
SEASON = "2025-26"
WEEK_START = date(2025, 11, 3)  # Monday
WEEK_END = date(2025, 11, 9)  # Sunday


def _roster_entry(key: str, name: str, abbr: str) -> RosterEntry:
    return RosterEntry(
        player_key=key, name=name, eligible_positions=["PG"], selected_position="PG",
        injury_status=None, nba_team_abbr=abbr,
    )


class _StubClient:
    def __init__(self, roster_by_team_week: dict[tuple[str, int], list[RosterEntry]]):
        self._roster_by_team_week = roster_by_team_week

    def get_scoreboard(self, league_key: str, week: int | None = None) -> list[Matchup]:
        if week != 1:
            return []
        return [
            Matchup(
                week=1,
                teams=[
                    MatchupTeam(team_key=TEAM_A_KEY, name="Team A", category_totals={}),
                    MatchupTeam(team_key=TEAM_B_KEY, name="Team B", category_totals={}),
                ],
            )
        ]

    def get_team_roster_for_week(self, team_key: str, week: int) -> list[RosterEntry]:
        return self._roster_by_team_week[(team_key, week)]


def _seed_league_and_teams(db_session) -> tuple[League, Team, Team]:
    league = League(
        yahoo_league_key=LEAGUE_KEY, name="Backtest League", season=2025,
        num_teams=2, scoring_type="head", settings_json={},
    )
    db_session.add(league)
    db_session.flush()
    team_a = Team(league_id=league.id, yahoo_team_key=TEAM_A_KEY, name="Team A", is_users_team=False)
    team_b = Team(league_id=league.id, yahoo_team_key=TEAM_B_KEY, name="Team B", is_users_team=False)
    db_session.add_all([team_a, team_b])
    db_session.flush()
    resolve_week(db_session, league, 1, yahoo_start=WEEK_START, yahoo_end=WEEK_END)
    return league, team_a, team_b


def _seed_schedule(db_session) -> None:
    # AAA plays 2 games in the week, BBB plays 3 -- both against a filler
    # opponent ("OPP") that never itself appears on a roster, so it can't be
    # mistaken for either real team's own game count
    aaa = NbaTeam(nba_team_id=9001, name="Team AAA", abbreviation="AAA")
    bbb = NbaTeam(nba_team_id=9002, name="Team BBB", abbreviation="BBB")
    opp = NbaTeam(nba_team_id=9999, name="Filler Opponent", abbreviation="OPP")
    db_session.add_all([aaa, bbb, opp])
    db_session.flush()

    games = [
        ("G1", date(2025, 11, 4), aaa, opp),
        ("G2", date(2025, 11, 7), opp, aaa),
        ("G3", date(2025, 11, 3), bbb, opp),
        ("G4", date(2025, 11, 5), opp, bbb),
        ("G5", date(2025, 11, 8), bbb, opp),
    ]
    for game_id, game_date, home, away in games:
        db_session.add(
            NbaGame(
                nba_game_id=game_id, game_date=game_date, season=SEASON,
                home_team_id=home.id, away_team_id=away.id,
            )
        )
    db_session.flush()


def _seed_players(db_session) -> None:
    alpha = NbaPlayer(nba_person_id=101, full_name="Player Alpha")
    beta = NbaPlayer(nba_person_id=102, full_name="Player Beta")
    db_session.add_all([alpha, beta])
    db_session.flush()

    db_session.add_all(
        [
            PlayerSeasonAverage(
                nba_player_id=alpha.id, season=SEASON, games_played=70,
                fgm=10.0, fga=20.0, ftm=4.0, fta=5.0, tpm=2.0, pts=26.0,
                reb=8.0, ast=5.0, stl=1.0, blk=1.0, tov=3.0,
            ),
            PlayerSeasonAverage(
                nba_player_id=beta.id, season=SEASON, games_played=70,
                fgm=9.0, fga=20.0, ftm=6.0, fta=8.0, tpm=3.0, pts=25.0,
                reb=10.0, ast=4.0, stl=2.0, blk=0.0, tov=1.0,
            ),
        ]
    )
    db_session.flush()


def _seed_week_results(db_session, league: League, team_a: Team, team_b: Team) -> None:
    # hand-picked "reality" -- deliberately agrees with the projection on some
    # categories and disagrees on others (plus one exact tie), so the
    # anchored hit-rate below actually exercises both outcomes, not just a
    # trivially-always-right or always-wrong case
    db_session.add(
        WeekResult(
            league_id=league.id, team_id=team_a.id, week=1, result="loss",
            category_totals={
                "fg_pct": 0.48, "ft_pct": 0.70, "tpm": 10.0, "pts": 60.0, "reb": 20.0,
                "ast": 8.0, "stl": 3.0, "blk": 1.0, "tov": 8.0,
            },
        )
    )
    db_session.add(
        WeekResult(
            league_id=league.id, team_id=team_b.id, week=1, result="win",
            category_totals={
                "fg_pct": 0.46, "ft_pct": 0.75, "tpm": 8.0, "pts": 70.0, "reb": 20.0,
                "ast": 15.0, "stl": 5.0, "blk": 4.0, "tov": 5.0,
            },
        )
    )
    db_session.flush()


def _setup(db_session, *, with_unmapped_player: bool) -> _StubClient:
    league, team_a, team_b = _seed_league_and_teams(db_session)
    _seed_schedule(db_session)
    _seed_players(db_session)
    _seed_week_results(db_session, league, team_a, team_b)

    roster_a = [_roster_entry("466.p.1", "Player Alpha", "AAA")]
    if with_unmapped_player:
        roster_a.append(_roster_entry("466.p.99", "Nonexistent Player", "AAA"))
    roster_b = [_roster_entry("466.p.2", "Player Beta", "BBB")]
    return _StubClient({(TEAM_A_KEY, 1): roster_a, (TEAM_B_KEY, 1): roster_b})


# hand-computed expectation (see module docstring numbers in the PR/report):
# predicted margins (mine=A, games A=2/B=3): fg_pct +0.05 (A), ft_pct +0.05 (A),
# tpm -5 (B), pts -23 (B), reb -14 (B), ast -2 (B), stl -4 (B), blk +2 (A),
# tov (inverted) -3 (B, i.e. A loses on turnovers)
# actual margins: fg_pct +0.02 (A) -> correct; ft_pct -0.05 (B) -> wrong;
# tpm +2 (A) -> wrong; pts -10 (B) -> correct; reb 0 -> tie, excluded;
# ast -7 (B) -> correct; stl -2 (B) -> correct; blk -3 (B) -> wrong;
# tov (inverted, raw A=8/B=5) -3 (B) -> correct
# => 5 correct / 8 total (reb excluded) = 0.625 overall
_EXPECTED_PER_CATEGORY = {
    "fg_pct": CategoryHitRate(predicted_correct=1, ties_excluded=0, total=1),
    "ft_pct": CategoryHitRate(predicted_correct=0, ties_excluded=0, total=1),
    "tpm": CategoryHitRate(predicted_correct=0, ties_excluded=0, total=1),
    "pts": CategoryHitRate(predicted_correct=1, ties_excluded=0, total=1),
    "reb": CategoryHitRate(predicted_correct=0, ties_excluded=1, total=0),
    "ast": CategoryHitRate(predicted_correct=1, ties_excluded=0, total=1),
    "stl": CategoryHitRate(predicted_correct=1, ties_excluded=0, total=1),
    "blk": CategoryHitRate(predicted_correct=0, ties_excluded=0, total=1),
    "tov": CategoryHitRate(predicted_correct=1, ties_excluded=0, total=1),
}


def test_backtest_predicts_correctly_against_hand_computed_actuals(db_session):
    client = _setup(db_session, with_unmapped_player=False)

    report = run_matchup_backtest(db_session, client, LEAGUE_KEY, SEASON)

    assert report.per_category == _EXPECTED_PER_CATEGORY
    assert report.overall_correct == 5
    assert report.overall_total == 8
    assert report.overall_hit_rate == 0.625
    assert report.unmapped_by_team_week == []
    assert report.weeks_skipped == []


def test_backtest_counts_unmapped_player_without_changing_hit_rate(db_session):
    client = _setup(db_session, with_unmapped_player=True)

    report = run_matchup_backtest(db_session, client, LEAGUE_KEY, SEASON)

    # the unmapped player contributes nothing to Team A's projection (same
    # zero-contribution skip weekly.py's roster assembly already applies), so
    # the hand-computed hit rate is unaffected -- only the unmapped count changes
    assert report.per_category == _EXPECTED_PER_CATEGORY
    assert report.unmapped_by_team_week == [
        TeamWeekUnmapped(week=1, team_key=TEAM_A_KEY, count=1)
    ]


def test_backtest_raises_for_a_league_never_backfilled(db_session):
    import pytest

    with pytest.raises(ValueError, match="never.*synced|has not been synced"):
        run_matchup_backtest(db_session, _StubClient({}), "466.l.99999", SEASON)


def test_backtest_skips_week_missing_actual_result(db_session):
    league, team_a, team_b = _seed_league_and_teams(db_session)
    _seed_schedule(db_session)
    _seed_players(db_session)
    # only team A has a WeekResult row for week 1 -- team B's is missing
    db_session.add(
        WeekResult(
            league_id=league.id, team_id=team_a.id, week=1, result="win",
            category_totals={cat: 1.0 for cat in _EXPECTED_PER_CATEGORY},
        )
    )
    db_session.flush()
    client = _StubClient({})

    report = run_matchup_backtest(db_session, client, LEAGUE_KEY, SEASON)

    assert report.weeks_skipped == [SkippedBacktestWeek(week=1, reason="missing_actual_result")]
    assert report.overall_total == 0
