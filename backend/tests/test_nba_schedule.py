import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from ninecat.models import NbaGame, NbaTeam
from ninecat.warehouse.nba_schedule import back_to_backs_in_range, games_in_range, sync_schedule

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nba" / "sample_schedule.json"

BOS_NBA_TEAM_ID = 1610612738
BKN_NBA_TEAM_ID = 1610612751
NYK_NBA_TEAM_ID = 1610612752
MIA_NBA_TEAM_ID = 1610612748

# the exact 4 teams / 5 games sample_schedule.json produces -- scoping queries to
# these natural keys (rather than a bare select(NbaTeam)/select(NbaGame)) lets these
# tests prove "upserts, never duplicates" even when the shared dev database already
# carries unrelated committed rows (e.g. from a real dev-login/e2e run)
_FIXTURE_NBA_TEAM_IDS = [BOS_NBA_TEAM_ID, BKN_NBA_TEAM_ID, NYK_NBA_TEAM_ID, MIA_NBA_TEAM_ID]
_FIXTURE_GAME_IDS = ["0022500001", "0022500010", "0022500011", "0022500012", "0022500013"]

WEEK_START = date(2025, 11, 1)
WEEK_END = date(2025, 11, 7)


def _fixture_fetcher(season: str) -> list[dict]:
    """Test fetcher standing in for the real nba_api call: reads the hand-built fixture."""
    return json.loads(FIXTURE_PATH.read_text())


def test_sync_schedule_upserts_teams_and_games(db_session):
    sync_schedule(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    teams = db_session.execute(
        select(NbaTeam).where(NbaTeam.nba_team_id.in_(_FIXTURE_NBA_TEAM_IDS))
    ).scalars().all()
    games = db_session.execute(
        select(NbaGame).where(NbaGame.nba_game_id.in_(_FIXTURE_GAME_IDS))
    ).scalars().all()

    # 4 distinct teams appear across the fixture's home/away fields
    assert len(teams) == 4
    # 5 game rows in the fixture
    assert len(games) == 5


def test_games_in_range_returns_count_and_dates_for_known_week(db_session):
    sync_schedule(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    result = games_in_range(db_session, BOS_NBA_TEAM_ID, WEEK_START, WEEK_END)

    assert result.count == 3
    assert result.dates == [date(2025, 11, 3), date(2025, 11, 4), date(2025, 11, 6)]


def test_games_in_range_filters_by_team(db_session):
    sync_schedule(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    result = games_in_range(db_session, BKN_NBA_TEAM_ID, WEEK_START, WEEK_END)

    assert result.count == 1
    assert result.dates == [date(2025, 11, 5)]


def test_back_to_backs_in_range_finds_known_pair(db_session):
    sync_schedule(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    pairs = back_to_backs_in_range(db_session, BOS_NBA_TEAM_ID, WEEK_START, WEEK_END)

    assert pairs == [(date(2025, 11, 3), date(2025, 11, 4))]


def test_back_to_backs_in_range_empty_for_team_with_no_consecutive_games(db_session):
    sync_schedule(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    pairs = back_to_backs_in_range(db_session, BKN_NBA_TEAM_ID, WEEK_START, WEEK_END)

    assert pairs == []


def test_sync_schedule_is_idempotent_on_rerun(db_session):
    sync_schedule(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()
    sync_schedule(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    teams = db_session.execute(
        select(NbaTeam).where(NbaTeam.nba_team_id.in_(_FIXTURE_NBA_TEAM_IDS))
    ).scalars().all()
    games = db_session.execute(
        select(NbaGame).where(NbaGame.nba_game_id.in_(_FIXTURE_GAME_IDS))
    ).scalars().all()

    assert len(teams) == 4
    assert len(games) == 5


def test_sync_schedule_rerun_with_changed_row_updates_in_place(db_session):
    # unmutated fixture equal-row rerun (above) would pass even under an
    # ON CONFLICT DO NOTHING upsert; this exercises the DO UPDATE branch
    # specifically by changing one game's date on the second sync and
    # asserting the existing row is updated rather than left stale/duplicated
    sync_schedule(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    first_game = db_session.execute(
        select(NbaGame).where(NbaGame.nba_game_id == "0022500013")
    ).scalar_one()
    assert first_game.game_date == date(2025, 11, 6)
    first_synced_at = first_game.synced_at

    def _mutated_fetcher(season: str) -> list[dict]:
        rows = json.loads(FIXTURE_PATH.read_text())
        for row in rows:
            if row["game_id"] == "0022500013":
                row["game_date"] = "2025-11-07"
        return rows

    sync_schedule(db_session, season="2025-26", fetcher=_mutated_fetcher)
    db_session.flush()
    # expire_all forces the next reads through postgres rather than the
    # session's identity map, so this actually proves the row was updated
    db_session.expire_all()

    teams = db_session.execute(
        select(NbaTeam).where(NbaTeam.nba_team_id.in_(_FIXTURE_NBA_TEAM_IDS))
    ).scalars().all()
    games = db_session.execute(
        select(NbaGame).where(NbaGame.nba_game_id.in_(_FIXTURE_GAME_IDS))
    ).scalars().all()
    assert len(teams) == 4
    assert len(games) == 5

    updated_game = db_session.execute(
        select(NbaGame).where(NbaGame.nba_game_id == "0022500013")
    ).scalar_one()
    assert updated_game.game_date == date(2025, 11, 7)
    # both syncs run inside the same test transaction, and Postgres's now()
    # is pinned to transaction start time, so this is >= rather than > —
    # still proves synced_at is driven by the upsert, not left at its
    # original server_default value
    assert updated_game.synced_at >= first_synced_at
