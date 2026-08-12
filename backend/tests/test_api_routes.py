import math
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from ninecat.api.routes import get_yahoo_client, router
from ninecat.auth.sessions import SESSION_COOKIE_NAME, create_session_cookie
from ninecat.config import get_settings
from ninecat.db import get_session
from ninecat.models import (
    League,
    NbaPlayer,
    PlayerIdMap,
    PlayerSeasonAverage,
    RosterSlot,
    Standing,
    Team,
    User,
    YahooToken,
)
from ninecat.yahoo.gateway import YahooAuthError, YahooUnavailableError
from ninecat.yahoo.parsers import (
    CategoryInfo,
    LeagueInfo,
    LeagueSettings,
    Matchup,
    MatchupTeam,
    RosterEntry,
    RosterPosition,
    StandingEntry,
    TeamInfo,
    UserTeamInfo,
)

LEAGUE_KEY = "466.l.1"
TEAM_KEY = "466.l.1.t.1"
RIVAL_TEAM_KEY = "466.l.1.t.2"

NINE_CATEGORIES = {"fg_pct", "ft_pct", "tpm", "pts", "reb", "ast", "stl", "blk", "tov"}


class _StubYahooClient:
    """Stands in for YahooClient in route tests -- no gateway, no network.

    Mirrors the _StubClient pattern in test_league_sync.py; each resource's
    return value (or raised error) is configurable per test.
    """

    def __init__(
        self,
        user_leagues=None,
        user_teams=None,
        settings_by_league=None,
        teams_by_league=None,
        standings_by_league=None,
        roster_by_team=None,
        scoreboard_by_league=None,
        raise_on_leagues=None,
        raise_on_scoreboard=None,
    ):
        self._user_leagues = user_leagues or []
        self._user_teams = user_teams or []
        self._settings_by_league = settings_by_league or {}
        self._teams_by_league = teams_by_league or {}
        self._standings_by_league = standings_by_league or {}
        self._roster_by_team = roster_by_team or {}
        self._scoreboard_by_league = scoreboard_by_league or {}
        self._raise_on_leagues = raise_on_leagues
        self._raise_on_scoreboard = raise_on_scoreboard

    def get_user_leagues(self):
        if self._raise_on_leagues is not None:
            raise self._raise_on_leagues
        return self._user_leagues

    def get_user_teams(self):
        return self._user_teams

    def get_league_settings(self, league_key):
        return self._settings_by_league[league_key]

    def get_league_teams(self, league_key):
        return self._teams_by_league[league_key]

    def get_standings(self, league_key):
        return self._standings_by_league[league_key]

    def get_team_roster(self, team_key):
        return self._roster_by_team.get(team_key, [])

    def get_scoreboard(self, league_key, week=None):
        if self._raise_on_scoreboard is not None:
            raise self._raise_on_scoreboard
        return self._scoreboard_by_league.get(league_key, [])


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


def _happy_path_client() -> _StubYahooClient:
    return _StubYahooClient(
        user_leagues=[
            LeagueInfo(
                league_key=LEAGUE_KEY,
                name="Nine Cat Nation",
                season="2026",
                scoring_type="head",
                num_teams=2,
            )
        ],
        user_teams=[UserTeamInfo(team_key=TEAM_KEY, league_key=LEAGUE_KEY)],
        settings_by_league={LEAGUE_KEY: _make_settings()},
        teams_by_league={
            LEAGUE_KEY: [
                TeamInfo(team_key=TEAM_KEY, name="My Team", logo_url=None, manager_name="Sanjae"),
                TeamInfo(team_key=RIVAL_TEAM_KEY, name="Rival", logo_url=None, manager_name="Jordan"),
            ]
        },
        standings_by_league={
            LEAGUE_KEY: [
                StandingEntry(team_key=TEAM_KEY, name="My Team", rank=1, wins=10, losses=2, ties=0),
                StandingEntry(team_key=RIVAL_TEAM_KEY, name="Rival", rank=2, wins=8, losses=4, ties=0),
            ]
        },
        roster_by_team={
            TEAM_KEY: [
                RosterEntry(
                    player_key="466.p.1",
                    name="LeBron James",
                    eligible_positions=["SF", "PF"],
                    selected_position="SF",
                    injury_status=None,
                    nba_team_abbr="LAL",
                ),
                RosterEntry(
                    player_key="466.p.2",
                    name="Unmapped Guy",
                    eligible_positions=["PG"],
                    selected_position="PG",
                    injury_status="GTD",
                    nba_team_abbr="BOS",
                ),
            ],
            RIVAL_TEAM_KEY: [],
        },
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=5,
                    teams=[
                        MatchupTeam(
                            team_key=TEAM_KEY, name="My Team", category_totals={12: "301", 19: "38"}
                        ),
                        MatchupTeam(
                            team_key=RIVAL_TEAM_KEY,
                            name="Rival",
                            category_totals={12: "289", 19: "44"},
                        ),
                    ],
                )
            ]
        },
    )


def _app(db_session, client) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_yahoo_client] = lambda: client
    return app


def _test_client(app: FastAPI) -> TestClient:
    # base_url must be https: set_session_on_response's cookie is secure=True,
    # and a plain-http TestClient (the default) silently drops secure cookies
    return TestClient(app, base_url="https://testserver")


def _seed_user(db_session, guid: str = "guid-1", name: str = "Sanjae") -> User:
    user = User(yahoo_guid=guid, display_name=name)
    db_session.add(user)
    db_session.flush()
    return user


def _authed_client(db_session, user: User, client: _StubYahooClient | None = None) -> TestClient:
    tc = _test_client(_app(db_session, client if client is not None else _StubYahooClient()))
    tc.cookies.set(SESSION_COOKIE_NAME, create_session_cookie(user.id))
    return tc


def _seed_league_with_team(db_session, user: User) -> tuple[League, Team, Team]:
    league = League(
        yahoo_league_key=LEAGUE_KEY,
        name="Nine Cat Nation",
        season=2026,
        num_teams=2,
        scoring_type="head",
        settings_json={},
    )
    db_session.add(league)
    db_session.flush()
    team = Team(
        league_id=league.id, yahoo_team_key=TEAM_KEY, name="My Team", is_users_team=True, user_id=user.id
    )
    rival = Team(league_id=league.id, yahoo_team_key=RIVAL_TEAM_KEY, name="Rival", is_users_team=False)
    db_session.add_all([team, rival])
    db_session.flush()
    return league, team, rival


# --- GET /api/me ---


def test_me_returns_display_name_and_linked_leagues(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)

    client = _authed_client(db_session, user)
    response = client.get("/api/me")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"display_name", "leagues"}
    assert body["display_name"] == user.display_name
    assert len(body["leagues"]) == 1
    entry = body["leagues"][0]
    assert set(entry.keys()) == {"id", "yahoo_league_key", "name", "season", "synced_at"}
    assert entry["id"] == league.id
    assert entry["yahoo_league_key"] == LEAGUE_KEY
    assert entry["season"] == "2026"
    datetime.fromisoformat(entry["synced_at"])


def test_me_excludes_leagues_not_linked_to_this_user(db_session):
    user = _seed_user(db_session, guid="guid-me", name="Me")
    other = _seed_user(db_session, guid="guid-other", name="Other")
    _seed_league_with_team(db_session, other)

    client = _authed_client(db_session, user)
    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.json()["leagues"] == []


# --- POST /api/sync ---


def test_sync_creates_leagues_links_team_and_maps_players(db_session):
    user = _seed_user(db_session)
    lebron = NbaPlayer(nba_person_id=2544, full_name="LeBron James")
    db_session.add(lebron)
    db_session.flush()
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=lebron.id,
            season=get_settings().current_season,
            games_played=50,
            fgm=10.0,
            fga=18.0,
            ftm=5.0,
            fta=6.0,
            tpm=2.0,
            pts=27.0,
            reb=7.5,
            ast=7.0,
            stl=1.2,
            blk=0.5,
            tov=3.0,
        )
    )
    db_session.flush()

    client = _authed_client(db_session, user, _happy_path_client())
    response = client.post("/api/sync")

    assert response.status_code == 200
    body = response.json()
    # POST /api/sync returns League[] directly (frontend/lib/api.ts syncLeagues),
    # not the wrapped MeResponse shape
    assert isinstance(body, list)
    assert len(body) == 1
    league_out = body[0]
    assert set(league_out.keys()) == {"id", "yahoo_league_key", "name", "season", "synced_at"}
    assert league_out["yahoo_league_key"] == LEAGUE_KEY
    assert league_out["season"] == "2026"

    team_row = db_session.execute(
        select(Team).where(Team.yahoo_team_key == TEAM_KEY)
    ).scalar_one()
    assert team_row.user_id == user.id
    assert team_row.is_users_team is True

    lebron_map = db_session.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "466.p.1")
    ).scalar_one()
    assert lebron_map.nba_player_id is not None
    unmapped_map = db_session.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "466.p.2")
    ).scalar_one()
    assert unmapped_map.nba_player_id is None


def test_sync_yahoo_auth_error_returns_401_with_reauth_detail(db_session):
    user = _seed_user(db_session)
    stub = _StubYahooClient(raise_on_leagues=YahooAuthError("no token"))
    client = _authed_client(db_session, user, stub)

    response = client.post("/api/sync")

    assert response.status_code == 401
    assert response.json()["detail"] == "yahoo_reauth_required"


def test_sync_yahoo_unavailable_error_returns_503(db_session):
    user = _seed_user(db_session)
    stub = _StubYahooClient(
        raise_on_leagues=YahooUnavailableError(stale_payload=None, synced_at=None)
    )
    client = _authed_client(db_session, user, stub)

    response = client.post("/api/sync")

    assert response.status_code == 503
    assert response.json()["detail"] == "yahoo_unavailable"


# --- GET /api/leagues/{id}/overview ---


def test_overview_returns_standings_and_matchup(db_session):
    user = _seed_user(db_session)
    league, team, rival = _seed_league_with_team(db_session, user)
    db_session.add_all(
        [
            Standing(league_id=league.id, team_id=team.id, rank=1, wins=10, losses=2, ties=0),
            Standing(league_id=league.id, team_id=rival.id, rank=2, wins=8, losses=4, ties=0),
        ]
    )
    db_session.flush()

    stub = _StubYahooClient(
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=5,
                    teams=[
                        MatchupTeam(team_key=TEAM_KEY, name="My Team", category_totals={12: "301"}),
                        MatchupTeam(team_key=RIVAL_TEAM_KEY, name="Rival", category_totals={12: "289"}),
                    ],
                )
            ]
        }
    )
    client = _authed_client(db_session, user, stub)
    response = client.get(f"/api/leagues/{league.id}/overview")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"standings", "matchup", "stale", "synced_at"}
    assert len(body["standings"]) == 2
    assert set(body["standings"][0].keys()) == {"team_id", "name", "rank", "wins", "losses", "ties"}
    assert body["standings"][0]["rank"] == 1
    assert body["standings"][0]["team_id"] == team.id
    # category_totals keys become JSON strings even though MatchupTeam stores int keys
    assert body["matchup"] == {
        "week": 5,
        "teams": [
            {"name": "My Team", "category_totals": {"12": "301"}},
            {"name": "Rival", "category_totals": {"12": "289"}},
        ],
    }
    assert body["stale"] is False
    datetime.fromisoformat(body["synced_at"])


def test_overview_scoreboard_unavailable_returns_null_matchup_and_stale_true(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)

    stub = _StubYahooClient(
        raise_on_scoreboard=YahooUnavailableError(stale_payload=None, synced_at=None)
    )
    client = _authed_client(db_session, user, stub)
    response = client.get(f"/api/leagues/{league.id}/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["matchup"] is None
    assert body["stale"] is True


def test_overview_offseason_no_user_matchup_returns_null_not_stale(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)

    stub = _StubYahooClient(
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=5,
                    teams=[
                        MatchupTeam(team_key="466.l.1.t.9", name="Someone Else", category_totals={}),
                        MatchupTeam(team_key="466.l.1.t.10", name="Another", category_totals={}),
                    ],
                )
            ]
        }
    )
    client = _authed_client(db_session, user, stub)
    response = client.get(f"/api/leagues/{league.id}/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["matchup"] is None
    assert body["stale"] is False


def test_overview_404_for_foreign_league(db_session):
    user = _seed_user(db_session, guid="guid-a", name="A")
    other = _seed_user(db_session, guid="guid-b", name="B")
    league, _team, _rival = _seed_league_with_team(db_session, other)

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/overview")

    assert response.status_code == 404


# --- GET /api/leagues/{id}/team ---


def test_team_returns_roster_with_averages_headshot_and_build_profile(db_session):
    user = _seed_user(db_session)
    league, team, _rival = _seed_league_with_team(db_session, user)

    lebron = NbaPlayer(nba_person_id=2544, full_name="LeBron James")
    db_session.add(lebron)
    db_session.flush()

    season = get_settings().current_season
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=lebron.id,
            season=season,
            games_played=50,
            fgm=10.0,
            fga=18.0,
            ftm=5.0,
            fta=6.0,
            tpm=2.0,
            pts=27.0,
            reb=7.5,
            ast=7.0,
            stl=1.2,
            blk=0.5,
            tov=3.0,
        )
    )
    db_session.add_all(
        [
            RosterSlot(
                team_id=team.id,
                yahoo_player_key="466.p.1",
                player_name="LeBron James",
                position="SF",
                injury_status=None,
            ),
            RosterSlot(
                team_id=team.id,
                yahoo_player_key="466.p.2",
                player_name="Unmapped Guy",
                position="PG",
                injury_status="GTD",
            ),
        ]
    )
    db_session.add(
        PlayerIdMap(
            nba_player_id=lebron.id,
            yahoo_player_key="466.p.1",
            yahoo_name="LeBron James",
            match_method="exact",
        )
    )
    db_session.add(
        PlayerIdMap(
            nba_player_id=None,
            yahoo_player_key="466.p.2",
            yahoo_name="Unmapped Guy",
            match_method="unmatched",
        )
    )
    db_session.flush()

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/team")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"roster", "build_profile", "stale", "synced_at"}
    assert body["stale"] is False
    datetime.fromisoformat(body["synced_at"])

    roster = {p["yahoo_player_key"]: p for p in body["roster"]}
    assert set(roster["466.p.1"].keys()) == {
        "yahoo_player_key",
        "name",
        "position",
        "injury_status",
        "headshot_url",
        "averages",
    }
    lebron_out = roster["466.p.1"]
    assert lebron_out["name"] == "LeBron James"
    assert lebron_out["position"] == "SF"
    assert lebron_out["headshot_url"] == "https://cdn.nba.com/headshots/nba/latest/1040x760/2544.png"
    assert lebron_out["averages"] is not None
    assert set(lebron_out["averages"].keys()) == NINE_CATEGORIES
    assert lebron_out["averages"]["fg_pct"] == round(10.0 / 18.0, 3)
    assert lebron_out["averages"]["pts"] == 27.0

    # unmapped player -> both averages and headshot_url must be null
    unmapped_out = roster["466.p.2"]
    assert unmapped_out["headshot_url"] is None
    assert unmapped_out["averages"] is None

    profile = body["build_profile"]
    assert set(profile.keys()) == {"totals", "labels", "means"}
    for key in ("totals", "labels", "means"):
        assert set(profile[key].keys()) == NINE_CATEGORIES

    # single-player population -> population std is 0, so every z-score is
    # exactly 0.0; means must not leak IEEE754 -0.0 (tov is the negated one)
    for value in profile["means"].values():
        assert value == 0.0
        assert math.copysign(1.0, value) == 1.0


def test_team_404_when_no_team_for_user(db_session):
    user = _seed_user(db_session)
    league = League(
        yahoo_league_key=LEAGUE_KEY,
        name="Nine Cat Nation",
        season=2026,
        num_teams=2,
        scoring_type="head",
        settings_json={},
    )
    db_session.add(league)
    db_session.flush()

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/team")

    assert response.status_code == 404


def test_team_404_for_foreign_league(db_session):
    user = _seed_user(db_session, guid="guid-a", name="A")
    other = _seed_user(db_session, guid="guid-b", name="B")
    league, _team, _rival = _seed_league_with_team(db_session, other)

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/team")

    assert response.status_code == 404


# --- POST /api/leagues/{id}/refresh ---


def test_refresh_reruns_sync_and_keeps_team_linked(db_session):
    user = _seed_user(db_session)
    league = League(
        yahoo_league_key=LEAGUE_KEY,
        name="stub",
        season=2026,
        num_teams=2,
        scoring_type="head",
        settings_json={},
    )
    db_session.add(league)
    db_session.flush()
    team = Team(league_id=league.id, yahoo_team_key=TEAM_KEY, name="stub", user_id=user.id)
    db_session.add(team)
    db_session.flush()

    client = _authed_client(db_session, user, _happy_path_client())
    response = client.post(f"/api/leagues/{league.id}/refresh")

    assert response.status_code == 204
    db_session.expire_all()
    fetched = db_session.get(League, league.id)
    assert len(fetched.settings_json["categories"]) == 9
    refreshed_team = db_session.execute(
        select(Team).where(Team.yahoo_team_key == TEAM_KEY)
    ).scalar_one()
    assert refreshed_team.user_id == user.id
    assert refreshed_team.is_users_team is True


def test_refresh_yahoo_auth_error_returns_401(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)

    class _RaisingClient(_StubYahooClient):
        def get_user_teams(self):
            raise YahooAuthError("no token")

    client = _authed_client(db_session, user, _RaisingClient())
    response = client.post(f"/api/leagues/{league.id}/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "yahoo_reauth_required"


def test_refresh_404_for_foreign_league(db_session):
    user = _seed_user(db_session, guid="guid-a", name="A")
    other = _seed_user(db_session, guid="guid-b", name="B")
    league, _team, _rival = _seed_league_with_team(db_session, other)

    client = _authed_client(db_session, user)
    response = client.post(f"/api/leagues/{league.id}/refresh")

    assert response.status_code == 404


# --- POST /api/account/disconnect ---


def test_disconnect_deletes_token_and_clears_cookie(db_session):
    user = _seed_user(db_session)
    db_session.add(
        YahooToken(
            user_id=user.id,
            encrypted_refresh_token="enc",
            access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    db_session.flush()

    client = _authed_client(db_session, user)
    response = client.post("/api/account/disconnect")

    assert response.status_code == 204
    assert (
        db_session.execute(
            select(YahooToken).where(YahooToken.user_id == user.id)
        ).scalar_one_or_none()
        is None
    )
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    assert cookie[SESSION_COOKIE_NAME].value == ""


# --- DELETE /api/account ---


def test_delete_account_removes_user_and_token_returns_204(db_session):
    user = _seed_user(db_session)
    db_session.add(
        YahooToken(
            user_id=user.id,
            encrypted_refresh_token="enc",
            access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    db_session.flush()
    user_id = user.id

    client = _authed_client(db_session, user)
    response = client.delete("/api/account")

    assert response.status_code == 204
    db_session.expire_all()
    assert db_session.get(User, user_id) is None
    assert (
        db_session.execute(
            select(YahooToken).where(YahooToken.user_id == user_id)
        ).scalar_one_or_none()
        is None
    )
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    assert cookie[SESSION_COOKIE_NAME].value == ""


# --- 401 without a session cookie, every endpoint ---


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/me"),
        ("post", "/api/sync"),
        ("get", "/api/leagues/1/overview"),
        ("get", "/api/leagues/1/team"),
        ("post", "/api/leagues/1/refresh"),
        ("post", "/api/account/disconnect"),
        ("delete", "/api/account"),
    ],
)
def test_endpoints_require_auth(db_session, method, path):
    client = _test_client(_app(db_session, _StubYahooClient()))
    response = getattr(client, method)(path)
    assert response.status_code == 401
