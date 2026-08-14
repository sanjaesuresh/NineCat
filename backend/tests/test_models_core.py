from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError, OperationalError

from ninecat.db import get_engine
from ninecat.models import FantasyWeek, League, RosterSlot, Team, User, WeekResult, YahooToken


def test_create_and_read_back_core_entities(db_session):
    user = User(yahoo_guid="yahoo-guid-1", display_name="Sanjae", email="sanjae@example.test")
    db_session.add(user)
    db_session.flush()

    token = YahooToken(
        user_id=user.id,
        encrypted_refresh_token="enc-refresh-token",
        access_token_expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(token)

    league = League(
        yahoo_league_key="nba.l.1",
        name="Test League",
        season=2026,
        num_teams=10,
        scoring_type="head",
        settings_json={"categories": ["PTS", "REB", "AST"]},
    )
    db_session.add(league)
    db_session.flush()

    team = Team(
        league_id=league.id,
        yahoo_team_key="nba.l.1.t.1",
        name="Sanjae's Squad",
        logo_url="https://example.test/logo.png",
        is_users_team=True,
        user_id=user.id,
    )
    db_session.add(team)
    db_session.flush()

    roster_slot = RosterSlot(
        team_id=team.id,
        yahoo_player_key="nba.p.1",
        player_name="Test Player",
        position="PG",
        nba_team_abbr="LAL",
    )
    db_session.add(roster_slot)
    db_session.commit()

    # expire_on_commit=False (conftest) means get() below would otherwise be served
    # from the identity map, not a real round-trip through postgres; force a reload
    db_session.expire_all()

    # read back
    fetched_user = db_session.get(User, user.id)
    assert fetched_user is not None
    assert fetched_user.yahoo_guid == "yahoo-guid-1"
    assert fetched_user.created_at is not None
    assert fetched_user.deleted_at is None

    fetched_token = db_session.get(YahooToken, token.id)
    assert fetched_token.user_id == user.id
    assert fetched_token.updated_at is not None

    fetched_league = db_session.get(League, league.id)
    assert fetched_league.synced_at is not None
    assert fetched_league.settings_json == {"categories": ["PTS", "REB", "AST"]}

    fetched_team = db_session.get(Team, team.id)
    assert fetched_team.league_id == league.id
    assert fetched_team.is_users_team is True

    fetched_roster_slot = db_session.get(RosterSlot, roster_slot.id)
    assert fetched_roster_slot.team_id == team.id
    assert fetched_roster_slot.injury_status is None
    assert fetched_roster_slot.synced_at is not None
    assert fetched_roster_slot.nba_team_abbr == "LAL"


def test_yahoo_guid_unique_constraint_rejects_duplicate(db_session):
    db_session.add(User(yahoo_guid="dup-guid", display_name="First"))
    db_session.flush()

    # bypass the ORM flush path for the deliberately-failing insert: Session.flush()'s
    # error handling rolls back the connection's outermost transaction regardless of any
    # savepoint nested under it, which would kill the fixture's own transaction and leave
    # its teardown rollback firing on an already-dead transaction (SAWarning). A Core-level
    # insert inside a Core-level SAVEPOINT confines the failure to just this statement.
    connection = db_session.connection()
    savepoint = connection.begin_nested()
    with pytest.raises(IntegrityError):
        connection.execute(
            insert(User.__table__).values(yahoo_guid="dup-guid", display_name="Second")
        )
    savepoint.rollback()


def test_roster_slot_nba_team_abbr_is_nullable(db_session):
    # a roster entry with no editorial_team_abbr (or one from a caller that
    # never set it) must store NULL, not crash or coerce to a sentinel
    league = League(
        yahoo_league_key="nba.l.abbr-null",
        name="Abbr Null League",
        season=2026,
        num_teams=10,
        scoring_type="head",
        settings_json={},
    )
    db_session.add(league)
    db_session.flush()
    team = Team(league_id=league.id, yahoo_team_key="nba.l.abbr-null.t.1", name="No Abbr", is_users_team=False)
    db_session.add(team)
    db_session.flush()

    slot = RosterSlot(team_id=team.id, yahoo_player_key="nba.p.no-abbr", player_name="No Abbr Guy", position="PG")
    db_session.add(slot)
    db_session.commit()
    db_session.expire_all()

    fetched = db_session.get(RosterSlot, slot.id)
    assert fetched.nba_team_abbr is None


def _make_league_and_team(db_session, key_suffix: str) -> tuple[League, Team]:
    league = League(
        yahoo_league_key=f"nba.l.{key_suffix}",
        name=f"League {key_suffix}",
        season=2026,
        num_teams=10,
        scoring_type="head",
        settings_json={},
    )
    db_session.add(league)
    db_session.flush()
    team = Team(
        league_id=league.id, yahoo_team_key=f"nba.l.{key_suffix}.t.1", name="Team", is_users_team=False
    )
    db_session.add(team)
    db_session.flush()
    return league, team


# --- FantasyWeek ---


def test_fantasy_week_round_trips_with_dates_and_source(db_session):
    league, _ = _make_league_and_team(db_session, "fw-1")

    week = FantasyWeek(
        league_id=league.id,
        week=3,
        start_date=date(2026, 1, 12),
        end_date=date(2026, 1, 18),
        date_source="yahoo",
    )
    db_session.add(week)
    db_session.commit()
    db_session.expire_all()

    fetched = db_session.get(FantasyWeek, week.id)
    assert fetched.league_id == league.id
    assert fetched.week == 3
    assert fetched.start_date == date(2026, 1, 12)
    assert fetched.end_date == date(2026, 1, 18)
    assert fetched.date_source == "yahoo"
    assert fetched.synced_at is not None


def test_fantasy_week_dates_and_source_nullable_for_known_but_undated_week(db_session):
    # a week can be known from the scoreboard before its dates are resolved --
    # the dateless/sourceless row is how that "known but not yet dated" state
    # is represented, not a fabricated placeholder date
    league, _ = _make_league_and_team(db_session, "fw-2")

    week = FantasyWeek(league_id=league.id, week=5)
    db_session.add(week)
    db_session.commit()
    db_session.expire_all()

    fetched = db_session.get(FantasyWeek, week.id)
    assert fetched.start_date is None
    assert fetched.end_date is None
    assert fetched.date_source is None


def test_fantasy_week_unique_constraint_rejects_duplicate_league_and_week(db_session):
    league, _ = _make_league_and_team(db_session, "fw-3")
    db_session.add(FantasyWeek(league_id=league.id, week=1, date_source="derived"))
    db_session.flush()

    connection = db_session.connection()
    savepoint = connection.begin_nested()
    with pytest.raises(IntegrityError):
        connection.execute(
            insert(FantasyWeek.__table__).values(
                league_id=league.id, week=1, date_source="derived"
            )
        )
    savepoint.rollback()


# --- WeekResult ---


def test_week_result_round_trips_category_totals_and_result(db_session):
    league, team = _make_league_and_team(db_session, "wr-1")

    result = WeekResult(
        league_id=league.id,
        team_id=team.id,
        week=4,
        category_totals={"1": "0.487", "4": "612", "9": "23"},
        result="win",
    )
    db_session.add(result)
    db_session.commit()
    db_session.expire_all()

    fetched = db_session.get(WeekResult, result.id)
    assert fetched.league_id == league.id
    assert fetched.team_id == team.id
    assert fetched.week == 4
    # JSONB round-trips object keys as strings, matching MatchupTeam.category_totals'
    # stat_id keys once serialized -- not coerced back to int
    assert fetched.category_totals == {"1": "0.487", "4": "612", "9": "23"}
    assert fetched.result == "win"
    assert fetched.synced_at is not None


def test_week_result_unique_constraint_rejects_duplicate_league_week_team(db_session):
    league, team = _make_league_and_team(db_session, "wr-2")
    db_session.add(
        WeekResult(league_id=league.id, team_id=team.id, week=2, category_totals={}, result="loss")
    )
    db_session.flush()

    connection = db_session.connection()
    savepoint = connection.begin_nested()
    with pytest.raises(IntegrityError):
        connection.execute(
            insert(WeekResult.__table__).values(
                league_id=league.id, team_id=team.id, week=2, category_totals={}, result="tie"
            )
        )
    savepoint.rollback()


# --- migration ---

BACKEND_DIR = Path(__file__).resolve().parents[1]
PRIOR_HEAD = "7329da112418"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_migration_upgrade_downgrade_upgrade_is_clean_with_single_head():
    # skip (not fail) on a machine/CI without postgres up, matching db_session's
    # own skip behavior elsewhere in this suite
    try:
        get_engine().connect().close()
    except OperationalError as exc:
        pytest.skip(f"Postgres unreachable: {exc}")

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1

    command.downgrade(cfg, PRIOR_HEAD)
    command.upgrade(cfg, "head")

    # leaves the db back at head so it doesn't strand the rest of the suite
    assert ScriptDirectory.from_config(cfg).get_current_head() is not None
