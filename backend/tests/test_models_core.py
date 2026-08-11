from datetime import datetime, timezone

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from ninecat.models import League, RosterSlot, Team, User, YahooToken


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
