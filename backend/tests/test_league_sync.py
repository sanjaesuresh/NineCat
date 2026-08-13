from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from ninecat.db import get_engine
from ninecat.models import League, RosterSlot, Standing, Team, User
from ninecat.sync.league_sync import sync_league_detail, sync_user_leagues
from ninecat.yahoo.parsers import (
    CategoryInfo,
    LeagueInfo,
    LeagueSettings,
    RosterEntry,
    RosterPosition,
    StandingEntry,
    TeamInfo,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
PRIOR_HEAD = "914838585199"


class _StubClient:
    """Stands in for YahooClient: returns canned dataclasses per league/team key,
    no network or gateway involved."""

    def __init__(
        self,
        user_leagues: list[LeagueInfo] | None = None,
        settings_by_league: dict[str, LeagueSettings] | None = None,
        teams_by_league: dict[str, list[TeamInfo]] | None = None,
        standings_by_league: dict[str, list[StandingEntry]] | None = None,
        roster_by_team: dict[str, list[RosterEntry]] | None = None,
    ):
        self._user_leagues = user_leagues or []
        self._settings_by_league = settings_by_league or {}
        self._teams_by_league = teams_by_league or {}
        self._standings_by_league = standings_by_league or {}
        self._roster_by_team = roster_by_team or {}

    def get_user_leagues(self) -> list[LeagueInfo]:
        return self._user_leagues

    def get_league_settings(self, league_key: str) -> LeagueSettings:
        return self._settings_by_league[league_key]

    def get_league_teams(self, league_key: str) -> list[TeamInfo]:
        return self._teams_by_league[league_key]

    def get_standings(self, league_key: str) -> list[StandingEntry]:
        return self._standings_by_league[league_key]

    def get_team_roster(self, team_key: str) -> list[RosterEntry]:
        return self._roster_by_team[team_key]


class _RosterRaisingClient(_StubClient):
    """Like _StubClient but raises when fetching one specific team's roster --
    proves roster reads are fully hoisted before any delete happens."""

    def __init__(self, *, raising_team_key: str, **kwargs):
        super().__init__(**kwargs)
        self._raising_team_key = raising_team_key

    def get_team_roster(self, team_key: str) -> list[RosterEntry]:
        if team_key == self._raising_team_key:
            raise RuntimeError("simulated mid-sync failure")
        return super().get_team_roster(team_key)


def _make_settings() -> LeagueSettings:
    # 9 real categories + one is_negative (TO), matching the yahoo 9-cat convention
    names = ["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
    categories = [
        CategoryInfo(stat_id=i + 1, name=name, display_name=name, is_negative=(name == "TO"))
        for i, name in enumerate(names)
    ]
    return LeagueSettings(
        categories=categories,
        roster_positions=[RosterPosition(position="PG", count=1)],
        max_weekly_adds=4,
        playoff_start_week=20,
        num_playoff_teams=4,
    )


def _make_teams() -> list[TeamInfo]:
    return [
        TeamInfo(team_key="466.l.1.t.1", name="Air Bud", logo_url="https://example.test/1.png", manager_name="Sanjae"),
        TeamInfo(team_key="466.l.1.t.2", name="Rebound City", logo_url=None, manager_name="Jordan"),
    ]


def _make_standings() -> list[StandingEntry]:
    return [
        StandingEntry(team_key="466.l.1.t.2", name="Rebound City", rank=1, wins=12, losses=3, ties=1),
        StandingEntry(team_key="466.l.1.t.1", name="Air Bud", rank=2, wins=8, losses=7, ties=0),
    ]


def _make_rosters() -> dict[str, list[RosterEntry]]:
    return {
        "466.l.1.t.1": [
            RosterEntry(
                player_key="466.p.1",
                name="LeBron James",
                eligible_positions=["SF", "PF"],
                selected_position="SF",
                injury_status="INJ",
                nba_team_abbr="LAL",
            ),
            RosterEntry(
                player_key="466.p.2",
                name="Nikola Jokic",
                eligible_positions=["C"],
                selected_position="C",
                injury_status=None,
                nba_team_abbr="DEN",
            ),
        ],
        "466.l.1.t.2": [],
    }


def _detail_client(users_team_key: str | None = None) -> _StubClient:
    return _StubClient(
        settings_by_league={"466.l.1": _make_settings()},
        teams_by_league={"466.l.1": _make_teams()},
        standings_by_league={"466.l.1": _make_standings()},
        roster_by_team=_make_rosters(),
    )


def _make_league(session, key="466.l.1") -> League:
    league = League(
        yahoo_league_key=key, name="stub", season=2026, num_teams=2, scoring_type="head", settings_json={}
    )
    session.add(league)
    session.flush()
    return league


# --- sync_user_leagues ---


def test_sync_user_leagues_creates_league_rows(db_session):
    user = User(yahoo_guid="guid-1", display_name="Sanjae")
    db_session.add(user)
    db_session.flush()
    client = _StubClient(
        user_leagues=[
            LeagueInfo(league_key="466.l.1", name="Nine Cat Nation", season="2026", scoring_type="head", num_teams=10)
        ]
    )

    leagues = sync_user_leagues(db_session, client, user.id)
    db_session.flush()

    assert len(leagues) == 1
    assert leagues[0].name == "Nine Cat Nation"
    assert leagues[0].yahoo_league_key == "466.l.1"
    assert leagues[0].synced_at is not None

    # scope the count check to this test's own key, not the whole table -- a
    # shared dev database can carry unrelated committed leagues (e.g. from a
    # real e2e run) that a bare `select(League)` count would wrongly trip over
    rows = db_session.scalars(select(League).where(League.yahoo_league_key == "466.l.1")).all()
    assert len(rows) == 1


def test_sync_user_leagues_rerun_updates_renamed_league_in_place(db_session):
    user = User(yahoo_guid="guid-2", display_name="Sanjae")
    db_session.add(user)
    db_session.flush()
    client = _StubClient(
        user_leagues=[
            LeagueInfo(league_key="466.l.1", name="Original Name", season="2026", scoring_type="head", num_teams=10)
        ]
    )
    sync_user_leagues(db_session, client, user.id)
    db_session.flush()

    # rename AND change season/num_teams/scoring_type -- all four in-place fields
    # must update, not just the one the test name calls out
    renamed_client = _StubClient(
        user_leagues=[
            LeagueInfo(
                league_key="466.l.1",
                name="Renamed League",
                season="2027",
                scoring_type="roto",
                num_teams=12,
            )
        ]
    )
    sync_user_leagues(db_session, renamed_client, user.id)
    db_session.flush()
    db_session.expire_all()

    # scoped by key, not a bare table count -- proves the rerun updated the
    # SAME row in place rather than inserting a second one, without assuming
    # this is the only league in a shared dev database
    rows = db_session.scalars(select(League).where(League.yahoo_league_key == "466.l.1")).all()
    assert len(rows) == 1
    assert rows[0].name == "Renamed League"
    assert rows[0].season == 2027
    assert rows[0].num_teams == 12
    assert rows[0].scoring_type == "roto"


def test_sync_user_leagues_rerun_does_not_clear_settings_json_from_detail_sync(db_session):
    user = User(yahoo_guid="guid-settings", display_name="Sanjae")
    db_session.add(user)
    db_session.flush()
    client = _StubClient(
        user_leagues=[
            LeagueInfo(league_key="466.l.1", name="Nine Cat Nation", season="2026", scoring_type="head", num_teams=10)
        ]
    )
    leagues = sync_user_leagues(db_session, client, user.id)
    db_session.flush()

    sync_league_detail(db_session, _detail_client(), leagues[0].id)
    db_session.flush()

    # sync_user_leagues must never touch settings_json -- only sync_league_detail owns it
    sync_user_leagues(db_session, client, user.id)
    db_session.flush()
    db_session.expire_all()

    fetched = db_session.get(League, leagues[0].id)
    assert len(fetched.settings_json["categories"]) == 9


# --- sync_league_detail ---


def test_sync_league_detail_missing_league_raises_value_error(db_session):
    client = _detail_client()
    with pytest.raises(ValueError):
        sync_league_detail(db_session, client, league_id=999999)


def test_sync_league_detail_creates_settings_teams_standings_and_rosters(db_session):
    league = _make_league(db_session)
    client = _detail_client()

    sync_league_detail(db_session, client, league.id)
    db_session.flush()
    db_session.expire_all()

    fetched_league = db_session.get(League, league.id)
    categories = fetched_league.settings_json["categories"]
    assert len(categories) == 9
    to_category = next(c for c in categories if c["display_name"] == "TO")
    assert to_category["is_negative"] is True
    assert fetched_league.synced_at is not None

    teams = db_session.scalars(select(Team).where(Team.league_id == league.id)).all()
    assert len(teams) == 2
    rebound_city = next(t for t in teams if t.name == "Rebound City")
    assert rebound_city.logo_url is None
    air_bud = next(t for t in teams if t.name == "Air Bud")
    assert air_bud.logo_url == "https://example.test/1.png"

    standings = db_session.scalars(select(Standing).where(Standing.league_id == league.id)).all()
    assert len(standings) == 2
    rc_standing = next(s for s in standings if s.team_id == rebound_city.id)
    assert rc_standing.rank == 1
    assert rc_standing.wins == 12

    slots = db_session.scalars(select(RosterSlot).where(RosterSlot.team_id == air_bud.id)).all()
    assert len(slots) == 2
    lebron = next(s for s in slots if s.player_name == "LeBron James")
    assert lebron.injury_status == "INJ"
    jokic = next(s for s in slots if s.player_name == "Nikola Jokic")
    assert jokic.injury_status is None


def test_sync_league_detail_rerun_with_changed_roster_replaces_exactly(db_session):
    league = _make_league(db_session)
    client = _detail_client()
    sync_league_detail(db_session, client, league.id)
    db_session.flush()

    air_bud = db_session.scalars(select(Team).where(Team.yahoo_team_key == "466.l.1.t.1")).one()
    before = db_session.scalars(select(RosterSlot).where(RosterSlot.team_id == air_bud.id)).all()
    assert {s.player_name for s in before} == {"LeBron James", "Nikola Jokic"}

    # LeBron dropped, Anthony Davis added -- same team, changed roster
    changed_rosters = {
        "466.l.1.t.1": [
            RosterEntry(
                player_key="466.p.2",
                name="Nikola Jokic",
                eligible_positions=["C"],
                selected_position="C",
                injury_status=None,
                nba_team_abbr="DEN",
            ),
            RosterEntry(
                player_key="466.p.3",
                name="Anthony Davis",
                eligible_positions=["PF", "C"],
                selected_position="PF",
                injury_status="GTD",
                nba_team_abbr="LAL",
            ),
        ],
        "466.l.1.t.2": [],
    }
    # ranks/records flipped vs. the first sync -- not identical data, so an
    # in-place update is the only way these new values could appear
    changed_standings = [
        StandingEntry(team_key="466.l.1.t.2", name="Rebound City", rank=2, wins=10, losses=5, ties=0),
        StandingEntry(team_key="466.l.1.t.1", name="Air Bud", rank=1, wins=14, losses=1, ties=0),
    ]
    changed_client = _StubClient(
        settings_by_league={"466.l.1": _make_settings()},
        teams_by_league={"466.l.1": _make_teams()},
        standings_by_league={"466.l.1": changed_standings},
        roster_by_team=changed_rosters,
    )

    sync_league_detail(db_session, changed_client, league.id)
    db_session.flush()
    db_session.expire_all()

    after = db_session.scalars(select(RosterSlot).where(RosterSlot.team_id == air_bud.id)).all()
    names = {s.player_name for s in after}
    assert names == {"Nikola Jokic", "Anthony Davis"}
    assert "LeBron James" not in names
    # no duplicates left behind by the replace
    assert len(after) == len(set(s.yahoo_player_key for s in after))

    # standings updated in place -- row count stable, not doubled, and the
    # new (not the original) rank/wins values are what's actually stored
    rebound_city = db_session.scalars(select(Team).where(Team.yahoo_team_key == "466.l.1.t.2")).one()
    standings = db_session.scalars(select(Standing).where(Standing.league_id == league.id)).all()
    assert len(standings) == 2
    air_bud_standing = next(s for s in standings if s.team_id == air_bud.id)
    assert air_bud_standing.rank == 1
    assert air_bud_standing.wins == 14
    rc_standing = next(s for s in standings if s.team_id == rebound_city.id)
    assert rc_standing.rank == 2
    assert rc_standing.wins == 10


def test_sync_league_detail_roster_fetch_failure_leaves_prior_rosters_intact(db_session):
    league = _make_league(db_session)
    client = _detail_client()
    sync_league_detail(db_session, client, league.id)
    db_session.flush()

    air_bud = db_session.scalars(select(Team).where(Team.yahoo_team_key == "466.l.1.t.1")).one()
    before = {
        s.player_name
        for s in db_session.scalars(select(RosterSlot).where(RosterSlot.team_id == air_bud.id)).all()
    }
    assert before == {"LeBron James", "Nikola Jokic"}

    # get_league_teams returns Air Bud (t.1) before Rebound City (t.2), so t.2
    # is the "second team" whose roster fetch fails -- if reads weren't fully
    # hoisted before any delete, t.1's roster would already be gone by the
    # time this raises
    failing_client = _RosterRaisingClient(
        raising_team_key="466.l.1.t.2",
        settings_by_league={"466.l.1": _make_settings()},
        teams_by_league={"466.l.1": _make_teams()},
        standings_by_league={"466.l.1": _make_standings()},
        roster_by_team=_make_rosters(),
    )

    with pytest.raises(RuntimeError):
        sync_league_detail(db_session, failing_client, league.id)

    db_session.expire_all()
    after = {
        s.player_name
        for s in db_session.scalars(select(RosterSlot).where(RosterSlot.team_id == air_bud.id)).all()
    }
    assert after == before


def test_sync_league_detail_users_team_key_flags_only_matching_team(db_session):
    league = _make_league(db_session)
    client = _detail_client()

    sync_league_detail(db_session, client, league.id, users_team_key="466.l.1.t.2")
    db_session.flush()
    db_session.expire_all()

    teams = db_session.scalars(select(Team).where(Team.league_id == league.id)).all()
    rebound_city = next(t for t in teams if t.yahoo_team_key == "466.l.1.t.2")
    air_bud = next(t for t in teams if t.yahoo_team_key == "466.l.1.t.1")
    assert rebound_city.is_users_team is True
    assert air_bud.is_users_team is False


def test_sync_league_detail_users_team_key_none_rerun_preserves_prior_flag(db_session):
    league = _make_league(db_session)
    client = _detail_client()
    sync_league_detail(db_session, client, league.id, users_team_key="466.l.1.t.2")
    db_session.flush()

    # a later detail-only re-sync with no users_team_key must not clear the
    # flag a previous sync set
    sync_league_detail(db_session, client, league.id)
    db_session.flush()
    db_session.expire_all()

    rebound_city = db_session.scalars(select(Team).where(Team.yahoo_team_key == "466.l.1.t.2")).one()
    assert rebound_city.is_users_team is True


# --- migration ---


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
