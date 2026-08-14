import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from http.cookies import SimpleCookie

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from ninecat.api.routes import get_yahoo_client, router
from ninecat.auth.routes import (
    _DEV_POOL_PLAYERS,
    _get_or_create_nba_player,
    _get_or_create_projection,
    _get_or_create_season_average,
)
from ninecat.auth.sessions import SESSION_COOKIE_NAME, create_session_cookie
from ninecat.config import get_settings
from ninecat.db import get_session
from ninecat.engine import CATEGORIES
from ninecat.models import (
    League,
    NbaPlayer,
    NbaTeam,
    PlayerIdMap,
    PlayerProjection,
    PlayerSeasonAverage,
    RosterSlot,
    Standing,
    Team,
    User,
    YahooToken,
)
from ninecat.warehouse.nba_schedule import sync_schedule
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
    assert set(body.keys()) == {"standings", "my_team_id", "matchup", "stale", "synced_at"}
    assert len(body["standings"]) == 2
    assert set(body["standings"][0].keys()) == {"team_id", "name", "rank", "wins", "losses", "ties"}
    assert body["standings"][0]["rank"] == 1
    assert body["standings"][0]["team_id"] == team.id
    assert body["my_team_id"] == team.id
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
        ("get", "/api/leagues/1/draft/board"),
        ("post", "/api/leagues/1/draft/recommend"),
        ("post", "/api/account/disconnect"),
        ("delete", "/api/account"),
    ],
)
def test_endpoints_require_auth(db_session, method, path):
    client = _test_client(_app(db_session, _StubYahooClient()))
    response = getattr(client, method)(path)
    assert response.status_code == 401


# --- GET /api/leagues/{id}/draft/board ---

_DRAFT_STAT_DEFAULTS = dict(
    fgm=8.0, fga=16.0, ftm=4.0, fta=5.0, tpm=2.0,
    pts=22.0, reb=6.0, ast=4.0, stl=1.0, blk=0.5, tov=2.0,
)  # fmt: skip


def _seed_draft_player(
    db_session, person_id: int, name: str, position: str, *, games: int = 70, source: str | None = None, **stat_overrides
) -> NbaPlayer:
    """An unrostered NbaPlayer with either a PlayerProjection (source given)
    or a PlayerSeasonAverage (source omitted) for the current season."""
    season = get_settings().current_season
    stats = {**_DRAFT_STAT_DEFAULTS, **stat_overrides}
    player = NbaPlayer(nba_person_id=person_id, full_name=name, position=position)
    db_session.add(player)
    db_session.flush()
    if source is not None:
        db_session.add(
            PlayerProjection(
                nba_player_id=player.id, season=season, source=source, projected_games=games, **stats
            )
        )
    else:
        db_session.add(
            PlayerSeasonAverage(nba_player_id=player.id, season=season, games_played=games, **stats)
        )
    db_session.flush()
    return player


_DRAFT_BOARD_KEYS = {
    "player_key", "name", "position", "nba_person_id", "headshot_url", "best_class",
    "projected_games", "base", "vorp", "value", "replacement", "zscores", "stat_basis",
}  # fmt: skip


def test_draft_board_returns_ranked_pool_with_expected_shape(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    star = _seed_draft_player(db_session, 900201, "Star Player", "C", source="proj-a", pts=30, reb=12)
    bench = _seed_draft_player(db_session, 900202, "Bench Player", "C", source="proj-a", pts=8, reb=3)

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"players", "punt_suggestions", "source", "stale", "synced_at"}
    assert body["source"] == "proj-a"
    assert body["punt_suggestions"] == []  # no team roster seeded -> no basis for a suggestion
    datetime.fromisoformat(body["synced_at"])

    players = body["players"]
    assert {p["player_key"] for p in players} == {str(star.id), str(bench.id)}
    assert set(players[0].keys()) == _DRAFT_BOARD_KEYS
    assert set(players[0]["zscores"].keys()) == NINE_CATEGORIES
    # ranked by value desc; the higher-pts/reb line must come out on top
    assert players[0]["player_key"] == str(star.id)
    assert players[0]["value"] >= players[1]["value"]
    # "stat_basis" (projection vs season average) is distinct from the
    # top-level "source" (the projection source NAME) -- see I4
    assert players[0]["stat_basis"] == "projection"
    assert players[0]["nba_person_id"] == 900201
    assert players[0]["headshot_url"] == "https://cdn.nba.com/headshots/nba/latest/1040x760/900201.png"


def test_draft_board_404_for_foreign_league(db_session):
    user = _seed_user(db_session, guid="guid-a", name="A")
    other = _seed_user(db_session, guid="guid-b", name="B")
    league, _team, _rival = _seed_league_with_team(db_session, other)

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board")

    assert response.status_code == 404


def test_draft_board_tolerates_empty_settings_json(db_session):
    # _seed_league_with_team's league carries settings_json={} (never synced) --
    # compute_draft_values raises on a roster layout with zero recognized starter
    # slots, and the route must map this to DEFAULT_ROSTER_SLOTS instead of 500ing
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    _seed_draft_player(db_session, 900203, "Solo Player", "C")

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board")

    assert response.status_code == 200
    assert len(response.json()["players"]) == 1


def test_draft_board_defaults_num_teams_below_one_to_twelve(db_session):
    # a malformed/never-set num_teams must not feed a <1 value into
    # LeagueConfig (compute_draft_values raises ValueError on that) -- the
    # route defaults to a standard 12-team league instead of 500ing
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    league.num_teams = 0
    db_session.flush()
    _seed_draft_player(db_session, 900209, "Only Player", "C")

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board")

    assert response.status_code == 200
    assert len(response.json()["players"]) == 1


@pytest.mark.parametrize(
    "malformed_roster_positions",
    [
        [{"pos": "PG", "n": 1}],  # wrong dict keys
        [{"position": "PG", "count": "1"}],  # count is a string, not an int
        ["PG", "SG"],  # entries aren't dicts at all
    ],
)
def test_draft_board_tolerates_malformed_roster_positions(db_session, malformed_roster_positions):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    league.settings_json = {"roster_positions": malformed_roster_positions}
    db_session.flush()
    _seed_draft_player(db_session, 900210, "Solo Player", "C")

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board")

    assert response.status_code == 200
    assert len(response.json()["players"]) == 1


def test_draft_board_falls_back_to_season_average_when_no_projection(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    _seed_draft_player(db_session, 900204, "Average Only", "C")

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] is None  # no projections synced at all -> pure season-average board
    assert body["players"][0]["stat_basis"] == "season_average"


def test_draft_board_ambiguous_source_returns_400(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    _seed_draft_player(db_session, 900205, "Proj A Player", "C", source="source-a")
    _seed_draft_player(db_session, 900206, "Proj B Player", "C", source="source-b")

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "source-a" in detail
    assert "source-b" in detail


def test_draft_board_source_param_selects_explicitly(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    player_a = _seed_draft_player(db_session, 900207, "Proj A Player", "C", source="source-a")
    _seed_draft_player(db_session, 900208, "Proj B Player", "C", source="source-b")

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board", params={"source": "source-a"})

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "source-a"
    # the source-b player has no source-a projection and no season average of
    # its own -> excluded from this board entirely, not silently mis-valued
    assert {p["player_key"] for p in body["players"]} == {str(player_a.id)}


def test_draft_board_unknown_source_returns_400_naming_valid_sources(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    _seed_draft_player(db_session, 900213, "Proj A Player", "C", source="source-a")

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board", params={"source": "typo-source"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "typo-source" in detail
    assert "source-a" in detail


def test_draft_board_punt_param_changes_ordering(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    specs = [
        ("Player A", 900209, dict(fgm=9, fga=18, ftm=5, fta=6, tpm=1, pts=24, reb=4, ast=3, stl=1, blk=0.3, tov=2.5)),
        ("Player B", 900210, dict(fgm=6, fga=11, ftm=3, fta=4, tpm=0.5, pts=15, reb=11, ast=7, stl=1.8, blk=1.2, tov=2.0)),
        ("Player C", 900211, dict(fgm=5, fga=10, ftm=2, fta=3, tpm=1.0, pts=13, reb=5, ast=4, stl=0.9, blk=0.4, tov=1.8)),
        ("Player D", 900212, dict(fgm=4, fga=9, ftm=2, fta=3, tpm=0.8, pts=10, reb=4, ast=3, stl=0.7, blk=0.3, tov=1.5)),
    ]  # fmt: skip
    ids = {}
    for name, person_id, stats in specs:
        player = _seed_draft_player(db_session, person_id, name, "C", **stats)
        ids[name] = str(player.id)

    client = _authed_client(db_session, user)
    no_punt = client.get(f"/api/leagues/{league.id}/draft/board")
    punted = client.get(f"/api/leagues/{league.id}/draft/board", params={"punt": ["pts"]})

    assert no_punt.status_code == 200
    assert punted.status_code == 200
    no_punt_order = [p["player_key"] for p in no_punt.json()["players"]]
    punt_order = [p["player_key"] for p in punted.json()["players"]]

    # hand-verified via compute_draft_values directly against this exact pool:
    # punting pts swaps the #2/#3 spots (Player A's edge was pts-heavy)
    assert no_punt_order == [ids["Player B"], ids["Player A"], ids["Player C"], ids["Player D"]]
    assert punt_order == [ids["Player B"], ids["Player C"], ids["Player A"], ids["Player D"]]
    assert punt_order != no_punt_order


def test_draft_board_unknown_punt_category_returns_400(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    _seed_draft_player(db_session, 900214, "Solo Player", "C")

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board", params={"punt": ["not_a_cat"]})

    assert response.status_code == 400
    assert "not_a_cat" in response.json()["detail"]


def test_draft_board_punt_suggestions_emit_ordered_array_not_hash_order(db_session):
    user = _seed_user(db_session)
    league, team, _rival = _seed_league_with_team(db_session, user)

    # draftable pool (unrostered) -- gives suggest_punt_builds a real pool to
    # evaluate pool_delta against
    for i, stats in enumerate(
        [
            dict(fgm=9, fga=18, ftm=5, fta=6, tpm=1, pts=24, reb=4, ast=3, stl=1, blk=0.3, tov=2.5),
            dict(fgm=6, fga=11, ftm=3, fta=4, tpm=0.5, pts=15, reb=11, ast=7, stl=1.8, blk=1.2, tov=2.0),
            dict(fgm=5, fga=10, ftm=2, fta=3, tpm=1.0, pts=13, reb=5, ast=4, stl=0.9, blk=0.4, tov=1.8),
        ]
    ):
        _seed_draft_player(db_session, 900301 + i, f"Pool Player {i}", "C", **stats)

    # the user's own roster: two low-FT-volume, high-block bigs -- a classic
    # punt-FT% profile, so suggest_punt_builds has a real weakness to surface
    roster_stats = dict(
        fgm=6.0, fga=9.0, ftm=1.0, fta=2.0, tpm=0.0,
        pts=13.0, reb=10.0, ast=1.5, stl=0.6, blk=1.8, tov=1.6,
    )  # fmt: skip
    roster_player_ids = []
    for i in range(2):
        person_id = 900401 + i
        player = NbaPlayer(nba_person_id=person_id, full_name=f"Roster Big {i}", position="C")
        db_session.add(player)
        db_session.flush()
        db_session.add(
            PlayerSeasonAverage(
                nba_player_id=player.id, season=get_settings().current_season, games_played=70, **roster_stats
            )
        )
        player_key = f"draft-test.p.{person_id}"
        db_session.add(
            RosterSlot(
                team_id=team.id, yahoo_player_key=player_key, player_name=player.full_name,
                position="C", injury_status=None,
            )
        )
        db_session.add(
            PlayerIdMap(
                nba_player_id=player.id, yahoo_player_key=player_key,
                yahoo_name=player.full_name, match_method="exact",
            )
        )
        roster_player_ids.append(str(player.id))
    db_session.flush()

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board")

    assert response.status_code == 200
    body = response.json()

    # rostered players are drafted/owned -- never appear in the draftable pool
    assert not ({p["player_key"] for p in body["players"]} & set(roster_player_ids))

    suggestions = body["punt_suggestions"]
    assert suggestions, "expected at least one punt suggestion from a real weak-FT roster"
    # pinned by value (not just sortedness) -- hand-verified via
    # suggest_punt_builds directly against this exact pool/roster
    assert suggestions[0]["punt"] == ["ft_pct", "tpm"]
    for suggestion in suggestions:
        assert set(suggestion.keys()) == {
            "punt", "score", "improvement", "pool_delta", "weakest", "weakest_mean", "rationale",
        }
        # regression guard: PuntSuggestion.punt is a frozenset (hash-order
        # iteration); the JSON array must be the stable punt_ordered form
        assert suggestion["punt"] == sorted(suggestion["punt"], key=CATEGORIES.index)
        assert set(suggestion["punt"]) <= set(CATEGORIES)

    # ?punt= only re-ranks the board -- punt_suggestions are always built off
    # the user's actual roster, independent of that re-ranking param
    punted = client.get(f"/api/leagues/{league.id}/draft/board", params={"punt": ["tov"]})
    assert punted.status_code == 200
    assert punted.json()["punt_suggestions"] == suggestions


def _seed_dev_pool_with_positions(db_session, *, position_overrides: dict[str, str | None] | None = None):
    """Seeds the real dev-seed draftable pool (72 recognizable players), with
    an optional per-name position override -- used by the plausibility test
    itself (real positions) and by its mutation-verification harness (every
    position forced to None, reproducing the T1-coalesce / T5-distribution
    failure class the test exists to catch)."""
    position_overrides = position_overrides or {}
    season = get_settings().current_season
    ids_by_name = {}
    for spec in _DEV_POOL_PLAYERS:
        position = position_overrides.get(spec["name"], spec["position"])
        player = _get_or_create_nba_player(
            db_session, person_id=spec["person_id"], full_name=spec["name"], position=position
        )
        _get_or_create_season_average(
            db_session, nba_player_id=player.id, season=season,
            averages=spec["averages"], games_played=spec["games"],
        )
        _get_or_create_projection(
            db_session, nba_player_id=player.id, season=season, source="dev-seed",
            projected_games=spec["games"], averages=spec["averages"],
        )
        ids_by_name[spec["name"]] = player.id
    return ids_by_name


def test_draft_board_ranks_elite_players_plausibly(db_session):
    """Regression guard for the position-distribution bug fixed in T5: seeds
    the real dev-seed draftable pool (72 recognizable players) and asserts
    the top of the board reads like a knowledgeable fan would expect, not
    distorted by a thin per-position replacement level (e.g. Mobley top-10),
    AND that the ranking is actually position-sensitive (best_class spans
    real positions, no single class dominates the top 10) -- a pure stat-line
    coincidence (e.g. every position collapsed to the same UTIL fallback)
    would still pass a Jokic-#1/Mobley-not-top-10 check on this stat data,
    so those two signals alone don't prove the position column is doing
    anything. Mutation-verified: forcing every seeded position to None makes
    the best_class assertions below fail (see fix-notes for the transcript)."""
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    league.num_teams = 12  # DEFAULT_ROSTER_SLOTS applies automatically (settings_json={})
    db_session.flush()

    ids_by_name = _seed_dev_pool_with_positions(db_session)

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/draft/board")

    assert response.status_code == 200
    players = response.json()["players"]
    top10_keys = [p["player_key"] for p in players[:10]]

    assert players[0]["player_key"] == str(ids_by_name["Nikola Jokic"])
    assert str(ids_by_name["Evan Mobley"]) not in top10_keys

    # the signal that actually moves under the T1/T5 bug class: best_class
    # (and the per-class replacement it drives) must reflect real position
    # eligibility, not collapse everyone into one bucket
    best_classes = {p["best_class"] for p in players}
    assert best_classes >= {"PG", "SG", "SF", "PF", "C"}
    top10_best_class_counts = Counter(p["best_class"] for p in players[:10])
    assert max(top10_best_class_counts.values()) <= 7


def test_draft_board_my_player_key_overrides_absent_yahoo_roster(db_session):
    # pre-draft, the user's actual Yahoo roster is empty -> punt_suggestions
    # would normally be [] (see test_draft_board_returns_ranked_pool_with_expected_shape);
    # ?my_player_key= lets a mock draft supply its own picks as the basis instead
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)

    for i, stats in enumerate(
        [
            dict(fgm=9, fga=18, ftm=5, fta=6, tpm=1, pts=24, reb=4, ast=3, stl=1, blk=0.3, tov=2.5),
            dict(fgm=6, fga=11, ftm=3, fta=4, tpm=0.5, pts=15, reb=11, ast=7, stl=1.8, blk=1.2, tov=2.0),
            dict(fgm=5, fga=10, ftm=2, fta=3, tpm=1.0, pts=13, reb=5, ast=4, stl=0.9, blk=0.4, tov=1.8),
        ]
    ):
        _seed_draft_player(db_session, 900501 + i, f"Pool Player {i}", "C", **stats)

    # poor-FT, high-block bigs -- classic punt-FT% profile, but only "mock
    # drafted" (never actually rostered on Yahoo, since the draft hasn't happened)
    roster_stats = dict(
        fgm=6.0, fga=9.0, ftm=1.0, fta=2.0, tpm=0.0,
        pts=13.0, reb=10.0, ast=1.5, stl=0.6, blk=1.8, tov=1.6,
    )  # fmt: skip
    bigs = [
        _seed_draft_player(db_session, 900511 + i, f"Mock Pick Big {i}", "C", **roster_stats)
        for i in range(2)
    ]

    client = _authed_client(db_session, user)
    no_key = client.get(f"/api/leagues/{league.id}/draft/board")
    assert no_key.status_code == 200
    assert no_key.json()["punt_suggestions"] == []

    with_key = client.get(
        f"/api/leagues/{league.id}/draft/board",
        params={"my_player_key": [str(b.id) for b in bigs]},
    )
    assert with_key.status_code == 200
    suggestions = with_key.json()["punt_suggestions"]
    assert suggestions, "expected a punt suggestion from the mock-draft roster override"
    assert any("ft_pct" in s["punt"] for s in suggestions)


def test_draft_board_my_player_key_overrides_present_yahoo_roster(db_session):
    # when both a real Yahoo roster AND ?my_player_key= are present, the
    # override wins -- a mock-draft session shouldn't be stuck advising off
    # last season's actual roster
    user = _seed_user(db_session)
    league, team, _rival = _seed_league_with_team(db_session, user)

    for i, stats in enumerate(
        [
            dict(fgm=9, fga=18, ftm=5, fta=6, tpm=1, pts=24, reb=4, ast=3, stl=1, blk=0.3, tov=2.5),
            dict(fgm=6, fga=11, ftm=3, fta=4, tpm=0.5, pts=15, reb=11, ast=7, stl=1.8, blk=1.2, tov=2.0),
            dict(fgm=5, fga=10, ftm=2, fta=3, tpm=1.0, pts=13, reb=5, ast=4, stl=0.9, blk=0.4, tov=1.8),
        ]
    ):
        _seed_draft_player(db_session, 900521 + i, f"Pool Player {i}", "C", **stats)

    # actual Yahoo roster: poor-FT, high-block bigs (same profile pinned by
    # test_draft_board_punt_suggestions_emit_ordered_array_not_hash_order to
    # suggest ["ft_pct", "tpm"])
    roster_stats = dict(
        fgm=6.0, fga=9.0, ftm=1.0, fta=2.0, tpm=0.0,
        pts=13.0, reb=10.0, ast=1.5, stl=0.6, blk=1.8, tov=1.6,
    )  # fmt: skip
    for i in range(2):
        person_id = 900531 + i
        player = NbaPlayer(nba_person_id=person_id, full_name=f"Roster Big {i}", position="C")
        db_session.add(player)
        db_session.flush()
        db_session.add(
            PlayerSeasonAverage(
                nba_player_id=player.id, season=get_settings().current_season, games_played=70, **roster_stats
            )
        )
        player_key = f"draft-test.p.{person_id}"
        db_session.add(
            RosterSlot(
                team_id=team.id, yahoo_player_key=player_key, player_name=player.full_name,
                position="C", injury_status=None,
            )
        )
        db_session.add(
            PlayerIdMap(
                nba_player_id=player.id, yahoo_player_key=player_key,
                yahoo_name=player.full_name, match_method="exact",
            )
        )
    db_session.flush()

    # override roster: excellent FT shooters, weak playmakers -- the opposite
    # of a punt-FT profile
    override_stats = dict(
        fgm=9.0, fga=15.0, ftm=8.0, fta=9.0, tpm=0.2,
        pts=26.0, reb=5.0, ast=0.5, stl=0.4, blk=0.2, tov=3.5,
    )  # fmt: skip
    override_players = [
        _seed_draft_player(db_session, 900541 + i, f"Mock Pick Wing {i}", "SF", **override_stats)
        for i in range(2)
    ]

    client = _authed_client(db_session, user)
    default = client.get(f"/api/leagues/{league.id}/draft/board")
    assert default.status_code == 200
    default_suggestions = default.json()["punt_suggestions"]
    assert default_suggestions, "expected a punt suggestion from the actual poor-FT roster"
    # the actual roster's clearest weakness is ft_pct -- the override wings
    # below (89% FT shooters) must never surface it (exact 2nd category isn't
    # pinned here; this test's pool composition differs slightly from the
    # ordered-array test that pins the full ["ft_pct", "tpm"] tuple)
    assert "ft_pct" in default_suggestions[0]["punt"]

    overridden = client.get(
        f"/api/leagues/{league.id}/draft/board",
        params={"my_player_key": [str(p.id) for p in override_players]},
    )
    assert overridden.status_code == 200
    overridden_suggestions = overridden.json()["punt_suggestions"]
    assert overridden_suggestions != default_suggestions
    # elite FT shooters have no business punting FT%
    assert all("ft_pct" not in s["punt"] for s in overridden_suggestions)


def test_draft_board_my_player_key_rejects_unknown_or_non_numeric(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    _seed_draft_player(db_session, 900550, "Solo Player", "C")

    client = _authed_client(db_session, user)
    response = client.get(
        f"/api/leagues/{league.id}/draft/board",
        params={"my_player_key": ["999999", "not-a-number"]},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "999999" in detail
    assert "not-a-number" in detail


def test_draft_board_my_player_key_does_not_change_ranked_players(db_session):
    # my_player_key affects punt_suggestions only -- the board's separate
    # ?punt= param is the only thing meant to re-rank the players list, so the
    # ranked list (and its ordering) must be byte-identical with or without it
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    specs = [
        (900560, dict(fgm=9, fga=18, ftm=5, fta=6, tpm=1, pts=24, reb=4, ast=3, stl=1, blk=0.3, tov=2.5)),
        (900561, dict(fgm=6, fga=11, ftm=3, fta=4, tpm=0.5, pts=15, reb=11, ast=7, stl=1.8, blk=1.2, tov=2.0)),
        (900562, dict(fgm=5, fga=10, ftm=2, fta=3, tpm=1.0, pts=13, reb=5, ast=4, stl=0.9, blk=0.4, tov=1.8)),
    ]  # fmt: skip
    ids = [_seed_draft_player(db_session, pid, f"Cand {pid}", "C", **stats).id for pid, stats in specs]

    client = _authed_client(db_session, user)
    no_key = client.get(f"/api/leagues/{league.id}/draft/board")
    with_key = client.get(
        f"/api/leagues/{league.id}/draft/board",
        params={"my_player_key": [str(pid) for pid in ids[:2]]},
    )

    assert no_key.status_code == 200
    assert with_key.status_code == 200
    assert with_key.json()["players"] == no_key.json()["players"]


# --- POST /api/leagues/{id}/draft/recommend ---


def _seed_recommend_pool(db_session) -> list[NbaPlayer]:
    specs = [
        (900601, dict(fgm=9, fga=18, ftm=5, fta=6, tpm=1, pts=24, reb=4, ast=3, stl=1, blk=0.3, tov=2.5)),
        (900602, dict(fgm=6, fga=11, ftm=3, fta=4, tpm=0.5, pts=15, reb=11, ast=7, stl=1.8, blk=1.2, tov=2.0)),
        (900603, dict(fgm=5, fga=10, ftm=2, fta=3, tpm=1.0, pts=13, reb=5, ast=4, stl=0.9, blk=0.4, tov=1.8)),
        (900604, dict(fgm=4, fga=9, ftm=2, fta=3, tpm=0.8, pts=10, reb=4, ast=3, stl=0.7, blk=0.3, tov=1.5)),
    ]  # fmt: skip
    return [
        _seed_draft_player(db_session, person_id, f"Cand {person_id}", "C", **stats)
        for person_id, stats in specs
    ]


def test_draft_recommend_round_trip(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    players = _seed_recommend_pool(db_session)

    client = _authed_client(db_session, user)
    response = client.post(
        f"/api/leagues/{league.id}/draft/recommend",
        json={"my_player_keys": [], "taken_player_keys": [], "overall_pick": 1, "limit": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"recommendations", "stale", "synced_at"}
    datetime.fromisoformat(body["synced_at"])
    recs = body["recommendations"]
    assert len(recs) == 2
    assert set(recs[0].keys()) == {
        "player_key", "name", "position", "value", "rank_score", "reasons", "need_cats",
    }
    assert recs[0]["player_key"] in {str(p.id) for p in players}


def test_draft_recommend_excludes_taken_and_mine(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    players = _seed_recommend_pool(db_session)
    taken = str(players[0].id)
    mine = str(players[1].id)

    client = _authed_client(db_session, user)
    response = client.post(
        f"/api/leagues/{league.id}/draft/recommend",
        json={
            "my_player_keys": [mine],
            "taken_player_keys": [taken],
            "overall_pick": 1,
            "limit": 10,
        },
    )

    assert response.status_code == 200
    returned_keys = {r["player_key"] for r in response.json()["recommendations"]}
    assert taken not in returned_keys
    assert mine not in returned_keys


def test_draft_recommend_honors_punt_and_source_body_params(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    for person_id, stats in [
        (900701, dict(fgm=9, fga=18, ftm=5, fta=6, tpm=1, pts=24, reb=4, ast=3, stl=1, blk=0.3, tov=2.5)),
        (900702, dict(fgm=6, fga=11, ftm=3, fta=4, tpm=0.5, pts=15, reb=11, ast=7, stl=1.8, blk=1.2, tov=2.0)),
    ]:
        _seed_draft_player(
            db_session, person_id, f"Cand {person_id}", "C", source="proj-x", **stats
        )

    client = _authed_client(db_session, user)
    response = client.post(
        f"/api/leagues/{league.id}/draft/recommend",
        json={"overall_pick": 1, "limit": 5, "source": "proj-x", "punt": ["pts"]},
    )

    assert response.status_code == 200
    assert len(response.json()["recommendations"]) == 2


def test_draft_recommend_unknown_punt_category_returns_400(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)
    _seed_draft_player(db_session, 900703, "Solo Player", "C")

    client = _authed_client(db_session, user)
    response = client.post(
        f"/api/leagues/{league.id}/draft/recommend",
        json={"overall_pick": 1, "punt": ["not_a_cat"]},
    )

    assert response.status_code == 400
    assert "not_a_cat" in response.json()["detail"]


def test_draft_recommend_excludes_league_rostered_players(db_session):
    # a player rostered on ANY team in the league is drafted/owned -- must
    # never show up in recommendations even if the client never listed it as
    # taken (the client's draft-state can't be trusted to know Yahoo reality)
    user = _seed_user(db_session)
    league, team, _rival = _seed_league_with_team(db_session, user)
    players = _seed_recommend_pool(db_session)
    rostered = players[0]
    player_key = "draft-test.p.rostered"
    db_session.add(
        RosterSlot(
            team_id=team.id, yahoo_player_key=player_key, player_name=rostered.full_name,
            position="C", injury_status=None,
        )
    )
    db_session.add(
        PlayerIdMap(
            nba_player_id=rostered.id, yahoo_player_key=player_key,
            yahoo_name=rostered.full_name, match_method="exact",
        )
    )
    db_session.flush()

    client = _authed_client(db_session, user)
    response = client.post(
        f"/api/leagues/{league.id}/draft/recommend",
        json={"overall_pick": 1, "limit": 10},
    )

    assert response.status_code == 200
    returned_keys = {r["player_key"] for r in response.json()["recommendations"]}
    assert str(rostered.id) not in returned_keys


def test_draft_recommend_404_for_foreign_league(db_session):
    user = _seed_user(db_session, guid="guid-a", name="A")
    other = _seed_user(db_session, guid="guid-b", name="B")
    league, _team, _rival = _seed_league_with_team(db_session, other)

    client = _authed_client(db_session, user)
    response = client.post(f"/api/leagues/{league.id}/draft/recommend", json={"overall_pick": 1})

    assert response.status_code == 404


def test_draft_recommend_rejects_overall_pick_below_one(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)

    client = _authed_client(db_session, user)
    response = client.post(f"/api/leagues/{league.id}/draft/recommend", json={"overall_pick": 0})

    assert response.status_code == 400


def test_draft_recommend_rejects_limit_out_of_range(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)

    client = _authed_client(db_session, user)
    too_low = client.post(
        f"/api/leagues/{league.id}/draft/recommend", json={"overall_pick": 1, "limit": 0}
    )
    too_high = client.post(
        f"/api/leagues/{league.id}/draft/recommend", json={"overall_pick": 1, "limit": 51}
    )

    assert too_low.status_code == 400
    assert too_high.status_code == 400


def test_draft_recommend_rejects_unknown_player_keys(db_session):
    user = _seed_user(db_session)
    league, _team, _rival = _seed_league_with_team(db_session, user)

    client = _authed_client(db_session, user)
    response = client.post(
        f"/api/leagues/{league.id}/draft/recommend",
        json={"overall_pick": 1, "my_player_keys": ["999999"], "taken_player_keys": ["not-a-number"]},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "999999" in detail
    assert "not-a-number" in detail


# --- GET /api/leagues/{id}/matchup ---

# fantasy week 5 under Settings.fantasy_season_start (2025-10-20, a Monday) --
# hand-verified equal to warehouse.fantasy_weeks.derive_week_range(5), so the
# derived-dates test and the explicit-yahoo-dates test share these exact
# literals rather than risking two independently-computed date sets drifting
MATCHUP_WEEK = 5
MATCHUP_WEEK_START = date(2025, 11, 17)
MATCHUP_WEEK_END = date(2025, 11, 23)

# 3 real NBA teams per side so games_in_range has something to count;
# distinct abbreviations from the LEAGUE_KEY/TEAM_KEY fixtures used elsewhere
# in this file, but real nba.com team ids (sync_schedule upserts NbaTeam by
# that id, so a made-up id would silently create a bogus team row)
_MATCHUP_NBA_TEAM_IDS = {
    "BOS": 1610612738,
    "LAL": 1610612747,
    "DAL": 1610612742,
    "MIA": 1610612748,
    "DEN": 1610612743,
    "OKC": 1610612760,
}
# (day offset from base_date, home abbr, away abbr) -- gives every team 2-3
# games in a 7-day window so per-side totals differ meaningfully
_MATCHUP_GAMES = [
    (0, "BOS", "LAL"), (1, "DAL", "MIA"), (2, "BOS", "DEN"),
    (3, "LAL", "OKC"), (4, "DAL", "BOS"), (5, "MIA", "DEN"), (6, "OKC", "LAL"),
]  # fmt: skip


def _matchup_schedule_fetcher(base_date: date):
    def _fetch(season: str) -> list[dict]:
        rows = []
        for day_offset, home, away in _MATCHUP_GAMES:
            game_date = base_date + timedelta(days=day_offset)
            rows.append(
                {
                    "game_id": f"matchup-test-{game_date.isoformat()}-{home}-{away}",
                    "game_date": game_date.isoformat(),
                    "home_team_id": _MATCHUP_NBA_TEAM_IDS[home],
                    "home_team_name": home,
                    "home_team_abbreviation": home,
                    "away_team_id": _MATCHUP_NBA_TEAM_IDS[away],
                    "away_team_name": away,
                    "away_team_abbreviation": away,
                }
            )
        return rows

    return _fetch


def _seed_matchup_schedule(db_session, *, base_date: date = MATCHUP_WEEK_START) -> dict[str, int]:
    """Upserts NbaTeam/NbaGame rows via the real sync_schedule path (idempotent
    on re-run, unlike a raw NbaTeam(...) insert, which matters since other
    tests/agents may upsert the same real team ids concurrently) and returns
    abbreviation -> internal NbaTeam.id, the FK NbaPlayer.nba_team_id needs.
    `base_date` != MATCHUP_WEEK_START lets a test put real games outside the
    matchup week -- the "schedule not synced for this week yet" shape.
    """
    sync_schedule(
        db_session, season=get_settings().current_season, fetcher=_matchup_schedule_fetcher(base_date)
    )
    db_session.flush()
    teams = (
        db_session.execute(
            select(NbaTeam).where(NbaTeam.nba_team_id.in_(_MATCHUP_NBA_TEAM_IDS.values()))
        )
        .scalars()
        .all()
    )
    nba_id_to_abbr = {v: k for k, v in _MATCHUP_NBA_TEAM_IDS.items()}
    return {nba_id_to_abbr[t.nba_team_id]: t.id for t in teams}


def _seed_matchup_player(
    db_session,
    person_id: int,
    name: str,
    position: str,
    team_abbr: str,
    team_internal_id_by_abbr: dict[str, int],
    roster_team: Team,
    **stats,
) -> None:
    """An NbaPlayer with a season average, PlayerIdMap, and RosterSlot on
    `roster_team` -- the full chain _team_side walks to build a
    WeeklyPlayerRate. team_internal_id_by_abbr empty (no schedule seeded)
    leaves nba_team_id None, exercising the "can't resolve a team" path.
    """
    player = NbaPlayer(
        nba_person_id=person_id,
        full_name=name,
        position=position,
        nba_team_id=team_internal_id_by_abbr.get(team_abbr),
    )
    db_session.add(player)
    db_session.flush()
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=player.id, season=get_settings().current_season, games_played=70, **stats
        )
    )
    player_key = f"{LEAGUE_KEY}.p.{person_id}"
    db_session.add(
        PlayerIdMap(
            nba_player_id=player.id, yahoo_player_key=player_key, yahoo_name=name, match_method="exact"
        )
    )
    db_session.add(
        RosterSlot(
            team_id=roster_team.id,
            yahoo_player_key=player_key,
            player_name=name,
            position=position,
            injury_status=None,
        )
    )
    db_session.flush()


def _seed_full_matchup(
    db_session,
    user,
    *,
    with_schedule: bool = True,
    week_start: date | None = None,
    week_end: date | None = None,
):
    """A league with a guard-heavy "mine" roster and a big-heavy "rival"
    roster (deliberately different category shapes, per the plan's mandatory
    fan-plausibility test), each with a real NBA team assigned so the
    schedule wires through end to end. Returns (league, team, rival, stub).
    """
    league, team, rival = _seed_league_with_team(db_session, user)
    league.settings_json = {"max_weekly_adds": 3}
    db_session.flush()

    team_internal_id_by_abbr = _seed_matchup_schedule(db_session) if with_schedule else {}

    _seed_matchup_player(
        db_session, 910101, "Guard A", "PG", "BOS", team_internal_id_by_abbr, team,
        fgm=8.0, fga=17.0, ftm=4.0, fta=5.0, tpm=3.0, pts=23.0, reb=4.0, ast=8.0, stl=1.2, blk=0.2, tov=2.5,
    )
    _seed_matchup_player(
        db_session, 910102, "Guard B", "SG", "LAL", team_internal_id_by_abbr, team,
        fgm=7.0, fga=15.0, ftm=3.0, fta=4.0, tpm=2.5, pts=19.5, reb=3.0, ast=6.0, stl=1.0, blk=0.1, tov=2.0,
    )
    _seed_matchup_player(
        db_session, 910103, "Guard C", "PG", "DAL", team_internal_id_by_abbr, team,
        fgm=6.0, fga=13.0, ftm=3.0, fta=3.5, tpm=2.0, pts=17.0, reb=3.5, ast=5.0, stl=0.9, blk=0.2, tov=1.8,
    )
    _seed_matchup_player(
        db_session, 910201, "Big A", "C", "MIA", team_internal_id_by_abbr, rival,
        fgm=8.0, fga=13.0, ftm=3.0, fta=5.0, tpm=0.0, pts=19.0, reb=12.0, ast=1.5, stl=0.6, blk=2.2, tov=1.8,
    )
    _seed_matchup_player(
        db_session, 910202, "Big B", "C", "DEN", team_internal_id_by_abbr, rival,
        fgm=7.0, fga=11.0, ftm=2.5, fta=4.0, tpm=0.0, pts=16.5, reb=10.5, ast=1.2, stl=0.5, blk=1.8, tov=1.5,
    )
    _seed_matchup_player(
        db_session, 910203, "Big C", "PF", "OKC", team_internal_id_by_abbr, rival,
        fgm=6.5, fga=10.0, ftm=2.0, fta=3.5, tpm=0.0, pts=15.0, reb=9.5, ast=1.0, stl=0.4, blk=1.5, tov=1.3,
    )  # fmt: skip

    stub = _StubYahooClient(
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=MATCHUP_WEEK,
                    teams=[
                        MatchupTeam(team_key=TEAM_KEY, name="My Team", category_totals={}),
                        MatchupTeam(team_key=RIVAL_TEAM_KEY, name="Rival", category_totals={}),
                    ],
                    week_start=week_start,
                    week_end=week_end,
                )
            ]
        }
    )
    return league, team, rival, stub


def test_matchup_404_for_foreign_league(db_session):
    user = _seed_user(db_session, guid="guid-a", name="A")
    other = _seed_user(db_session, guid="guid-b", name="B")
    league, _team, _rival = _seed_league_with_team(db_session, other)

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/matchup")

    assert response.status_code == 404


def test_matchup_projects_both_sides_and_compares(db_session):
    user = _seed_user(db_session)
    league, _team, _rival, stub = _seed_full_matchup(
        db_session, user, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(
        f"/api/leagues/{league.id}/matchup", params={"as_of": MATCHUP_WEEK_START.isoformat()}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "week", "week_range", "as_of", "mine", "opponent", "opponent_reason",
        "comparison", "schedule_coverage", "streaming", "stale", "synced_at",
    }  # fmt: skip
    assert body["week"] == MATCHUP_WEEK
    assert body["week_range"] == {
        "start_date": MATCHUP_WEEK_START.isoformat(),
        "end_date": MATCHUP_WEEK_END.isoformat(),
        "is_derived": False,
    }
    assert body["opponent"] is not None
    assert body["opponent_reason"] is None
    assert body["mine"]["projection"]["games"] > 0
    assert body["opponent"]["projection"]["games"] > 0
    assert body["schedule_coverage"] == {
        "mine_games": body["mine"]["projection"]["games"],
        "opponent_games": body["opponent"]["projection"]["games"],
        "ok": True,
    }

    comparison = body["comparison"]
    assert comparison is not None
    mine_wins, their_wins = comparison["projected_score"]
    assert mine_wins + their_wins <= 9
    assert {cv["category"] for cv in comparison["categories"]} == NINE_CATEGORIES

    # no free agents seeded (the only draftable players are the 6 rostered
    # ones, all excluded) -- proves the streaming wiring runs end to end and
    # degrades gracefully rather than erroring on an empty candidate pool.
    # as_of falls inside the week -> "remaining days" basis, live-week behavior
    assert body["streaming"] == {
        "slots": [], "adds_used": 0, "adds_reserved": 0, "notes": ["no_candidates"],
        "window_basis": "remaining",
    }  # fmt: skip


def test_matchup_streaming_full_week_when_as_of_after_week_end(db_session):
    """The demo-blocking case: as_of (defaults to the real wall clock) can
    land AFTER a fixed/seeded week's end, not just before its start. The
    window must clamp INTO the week (plan the whole thing) rather than
    produce an empty invalid_window -- and a real free agent in a genuinely
    close category must still produce a non-empty plan end to end (the
    concrete non-empty case, distinct from the no-candidates empty path
    covered elsewhere)."""
    user = _seed_user(db_session)
    league, team, rival = _seed_league_with_team(db_session, user)
    league.settings_json = {"max_weekly_adds": 3}
    db_session.flush()

    team_internal_id_by_abbr = _seed_matchup_schedule(db_session)

    # identical stat lines, identical games (BOS and LAL both have 3 games in
    # _MATCHUP_GAMES) -> every non-zero category is an EXACT tie, which
    # compare_matchup still counts as "close" (a dead-level, flippable
    # category, distinct from the 0-0 missing-data case) -- guarantees
    # close_categories is the full 9, so any positive-value free agent scores
    tied_stats = dict(
        fgm=7.0, fga=15.0, ftm=3.0, fta=4.0, tpm=2.0, pts=19.0,
        reb=5.0, ast=4.0, stl=1.0, blk=0.5, tov=2.0,
    )  # fmt: skip
    _seed_matchup_player(db_session, 910401, "Mine One", "PG", "BOS", team_internal_id_by_abbr, team, **tied_stats)
    _seed_matchup_player(db_session, 910402, "Rival One", "PG", "LAL", team_internal_id_by_abbr, rival, **tied_stats)

    # a free agent -- not rostered on either team -- with games in the week
    # and all-around positive stats (low tov relative to everything else, so
    # its net signed value is clearly positive)
    fa = NbaPlayer(
        nba_person_id=910403, full_name="Free Agent One", position="SF",
        nba_team_id=team_internal_id_by_abbr["DAL"],
    )  # fmt: skip
    db_session.add(fa)
    db_session.flush()
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=fa.id, season=get_settings().current_season, games_played=70,
            fgm=6.0, fga=12.0, ftm=2.0, fta=2.5, tpm=1.5, pts=15.5,
            reb=6.0, ast=3.0, stl=1.0, blk=0.5, tov=1.5,
        )
    )  # fmt: skip
    db_session.flush()

    stub = _StubYahooClient(
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=MATCHUP_WEEK,
                    teams=[
                        MatchupTeam(team_key=TEAM_KEY, name="My Team", category_totals={}),
                        MatchupTeam(team_key=RIVAL_TEAM_KEY, name="Rival", category_totals={}),
                    ],
                    week_start=MATCHUP_WEEK_START,
                    week_end=MATCHUP_WEEK_END,
                )
            ]
        }
    )
    client = _authed_client(db_session, user, stub)

    # as_of is well after MATCHUP_WEEK_END (2025-11-23) -- the week is
    # entirely in the past relative to this "now"
    response = client.get(
        f"/api/leagues/{league.id}/matchup", params={"as_of": "2026-01-01"}
    )

    assert response.status_code == 200
    body = response.json()
    streaming = body["streaming"]
    assert streaming is not None
    assert streaming["window_basis"] == "full_week"
    assert streaming["slots"], "expected a non-empty plan for a genuinely close matchup with a viable free agent"
    assert streaming["slots"][0]["player_key"] == str(fa.id)
    # the plan covers the FULL week, not "remaining days from as_of" (which
    # would be empty/invalid since as_of is after week_end)
    assert date.fromisoformat(streaming["slots"][0]["day"]) >= MATCHUP_WEEK_START
    # regression guard: a streaming slot used to carry only player_key, which
    # rendered as "Player #<id>" on the page -- must carry the same display
    # fields the draft board/adds endpoint emit
    assert streaming["slots"][0]["name"] == "Free Agent One"
    assert streaming["slots"][0]["position"] == "SF"
    assert streaming["slots"][0]["nba_person_id"] == 910403
    assert streaming["slots"][0]["headshot_url"] == (
        "https://cdn.nba.com/headshots/nba/latest/1040x760/910403.png"
    )


def test_matchup_missing_schedule_flags_zero_games(db_session):
    user = _seed_user(db_session)
    league, _team, _rival, stub = _seed_full_matchup(
        db_session, user, with_schedule=False, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(f"/api/leagues/{league.id}/matchup")

    assert response.status_code == 200
    body = response.json()
    assert body["mine"]["projection"]["games"] == 0.0
    assert body["opponent"]["projection"]["games"] == 0.0
    assert body["schedule_coverage"] == {"mine_games": 0.0, "opponent_games": 0.0, "ok": False}
    # zero games -> every counting total is zero -- the guard flag above is
    # what tells the UI not to present this 0-0 comparison as real
    for cv in body["comparison"]["categories"]:
        assert cv["mine"] == 0.0
        assert cv["theirs"] == 0.0


def test_matchup_schedule_outside_week_range_also_flags_zero_games(db_session):
    """Distinct from the no-team-mapping case above: NbaTeam/NbaGame rows
    exist (player -> team resolves fine) but none of the synced games fall
    inside this specific matchup week -- the realistic "schedule sync is
    stale for this week" shape the guard exists to catch."""
    user = _seed_user(db_session)
    league, team, rival = _seed_league_with_team(db_session, user)
    team_internal_id_by_abbr = _seed_matchup_schedule(db_session, base_date=date(2026, 3, 2))
    _seed_matchup_player(
        db_session, 910301, "Guard A", "PG", "BOS", team_internal_id_by_abbr, team,
        fgm=8.0, fga=17.0, ftm=4.0, fta=5.0, tpm=3.0, pts=23.0, reb=4.0, ast=8.0, stl=1.2, blk=0.2, tov=2.5,
    )
    _seed_matchup_player(
        db_session, 910302, "Big A", "C", "MIA", team_internal_id_by_abbr, rival,
        fgm=8.0, fga=13.0, ftm=3.0, fta=5.0, tpm=0.0, pts=19.0, reb=12.0, ast=1.5, stl=0.6, blk=2.2, tov=1.8,
    )  # fmt: skip
    stub = _StubYahooClient(
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=MATCHUP_WEEK,
                    teams=[
                        MatchupTeam(team_key=TEAM_KEY, name="My Team", category_totals={}),
                        MatchupTeam(team_key=RIVAL_TEAM_KEY, name="Rival", category_totals={}),
                    ],
                    week_start=MATCHUP_WEEK_START,
                    week_end=MATCHUP_WEEK_END,
                )
            ]
        }
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(f"/api/leagues/{league.id}/matchup")

    assert response.status_code == 200
    body = response.json()
    assert body["schedule_coverage"]["ok"] is False
    assert body["mine"]["projection"]["games"] == 0.0


def test_matchup_derived_dates_flag_true_without_yahoo_week_dates(db_session):
    user = _seed_user(db_session)
    league, _team, _rival, stub = _seed_full_matchup(db_session, user)  # week_start/end default None
    client = _authed_client(db_session, user, stub)

    response = client.get(f"/api/leagues/{league.id}/matchup")

    assert response.status_code == 200
    body = response.json()
    assert body["week_range"] == {
        "start_date": MATCHUP_WEEK_START.isoformat(),
        "end_date": MATCHUP_WEEK_END.isoformat(),
        "is_derived": True,
    }


def test_matchup_no_opponent_when_matchup_has_only_my_team(db_session):
    user = _seed_user(db_session)
    league, _team, _rival, _stub = _seed_full_matchup(
        db_session, user, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    stub = _StubYahooClient(
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=MATCHUP_WEEK,
                    teams=[MatchupTeam(team_key=TEAM_KEY, name="My Team", category_totals={})],
                    week_start=MATCHUP_WEEK_START,
                    week_end=MATCHUP_WEEK_END,
                )
            ]
        }
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(f"/api/leagues/{league.id}/matchup")

    assert response.status_code == 200
    body = response.json()
    assert body["opponent"] is None
    assert body["opponent_reason"] == "no_opponent_in_matchup"
    assert body["comparison"] is None
    assert body["streaming"] is None
    # my own side still projects fine -- a missing opponent must never
    # degrade my own roster's numbers
    assert body["mine"]["projection"]["games"] > 0


def test_matchup_no_opponent_when_scoreboard_unavailable(db_session):
    user = _seed_user(db_session)
    league, _team, _rival, _stub = _seed_full_matchup(
        db_session, user, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    stub = _StubYahooClient(raise_on_scoreboard=YahooUnavailableError(stale_payload=None, synced_at=None))
    client = _authed_client(db_session, user, stub)

    response = client.get(f"/api/leagues/{league.id}/matchup", params={"week": MATCHUP_WEEK})

    assert response.status_code == 200
    body = response.json()
    assert body["opponent"] is None
    assert body["opponent_reason"] == "yahoo_unavailable"
    # ?week= was explicit, so the response still projects that week even
    # though the live scoreboard couldn't be reached for opponent/date info
    assert body["week"] == MATCHUP_WEEK
    assert body["week_range"]["is_derived"] is True


def test_matchup_percentages_match_components_not_double_divided(db_session):
    user = _seed_user(db_session)
    league, _team, _rival, stub = _seed_full_matchup(
        db_session, user, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(f"/api/leagues/{league.id}/matchup")
    body = response.json()

    for side in ("mine", "opponent"):
        totals = body[side]["projection"]["totals"]
        components = body[side]["projection"]["components"]
        expected_fg_pct = components["fgm"] / components["fga"] if components["fga"] else 0.0
        expected_ft_pct = components["ftm"] / components["fta"] if components["fta"] else 0.0
        assert totals["fg_pct"] == pytest.approx(expected_fg_pct, abs=0.01)
        assert totals["ft_pct"] == pytest.approx(expected_ft_pct, abs=0.01)


def test_matchup_fan_plausibility_guards_beat_bigs_in_ast_and_tpm(db_session):
    """Mandatory per the plan: proves the whole roster -> schedule -> rate ->
    projection pipeline is wired correctly, not just internally consistent
    arithmetic. A guard-heavy roster must out-project a big-heavy one in
    assists/3PM, and the reverse for rebounds/blocks."""
    user = _seed_user(db_session)
    league, _team, _rival, stub = _seed_full_matchup(
        db_session, user, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(f"/api/leagues/{league.id}/matchup")
    body = response.json()

    mine = body["mine"]["projection"]["totals"]
    theirs = body["opponent"]["projection"]["totals"]

    assert mine["ast"] > theirs["ast"]
    assert mine["tpm"] > theirs["tpm"]
    assert theirs["reb"] > mine["reb"]
    assert theirs["blk"] > mine["blk"]


# --- GET /api/leagues/{league_id}/adds ---


def test_adds_404_for_foreign_league(db_session):
    user = _seed_user(db_session, guid="guid-a", name="A")
    other = _seed_user(db_session, guid="guid-b", name="B")
    league, _team, _rival = _seed_league_with_team(db_session, other)

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/adds")

    assert response.status_code == 404


def test_adds_shape_no_free_agents(db_session):
    user = _seed_user(db_session)
    league, _team, _rival, stub = _seed_full_matchup(
        db_session, user, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(
        f"/api/leagues/{league.id}/adds", params={"as_of": MATCHUP_WEEK_START.isoformat()}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "week", "week_range", "as_of", "window_basis", "close_categories",
        "opponent_reason", "candidates", "schedule_coverage", "stale", "synced_at",
    }  # fmt: skip
    assert body["week"] == MATCHUP_WEEK
    assert body["week_range"] == {
        "start_date": MATCHUP_WEEK_START.isoformat(),
        "end_date": MATCHUP_WEEK_END.isoformat(),
        "is_derived": False,
    }
    assert body["opponent_reason"] is None
    assert set(body["close_categories"]) <= NINE_CATEGORIES
    assert body["window_basis"] == "remaining"
    assert body["schedule_coverage"]["ok"] is True
    # no free agents seeded (the only draftable players are the 6 rostered
    # ones, all excluded) -- proves the pool-building wiring degrades to an
    # empty list rather than erroring, mirroring the matchup endpoint's own
    # empty-streaming-pool test
    assert body["candidates"] == []


def test_adds_missing_schedule_returns_empty_candidates(db_session):
    user = _seed_user(db_session)
    league, _team, _rival, stub = _seed_full_matchup(
        db_session, user, with_schedule=False, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(f"/api/leagues/{league.id}/adds")

    assert response.status_code == 200
    body = response.json()
    assert body["schedule_coverage"] == {"mine_games": 0.0, "opponent_games": 0.0, "ok": False}
    assert body["candidates"] == []


def test_adds_no_opponent_degrades_to_need_only_ranking(db_session):
    """No opponent identifiable -> close_categories is empty and
    opponent_reason names why, but the list still ranks on roster need alone
    rather than going empty (plan requirement: a degraded matchup must still
    produce a usable list)."""
    user = _seed_user(db_session)
    league, team, _rival, _stub = _seed_full_matchup(
        db_session, user, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    # a free agent that helps this guard-heavy roster's real weaknesses
    # (reb/blk/tov) so the need-only ranking has a genuine positive-score
    # candidate to surface
    team_internal_id_by_abbr = _seed_matchup_schedule(db_session)
    fa = NbaPlayer(
        nba_person_id=961001, full_name="Need Helper", position="C",
        nba_team_id=team_internal_id_by_abbr["DAL"],
    )  # fmt: skip
    db_session.add(fa)
    db_session.flush()
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=fa.id, season=get_settings().current_season, games_played=70,
            fgm=6.0, fga=11.0, ftm=2.0, fta=3.0, tpm=0.0, pts=14.0,
            reb=7.0, ast=1.5, stl=0.6, blk=1.5, tov=1.2,
        )
    )  # fmt: skip
    db_session.flush()

    stub = _StubYahooClient(
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=MATCHUP_WEEK,
                    teams=[MatchupTeam(team_key=TEAM_KEY, name="My Team", category_totals={})],
                    week_start=MATCHUP_WEEK_START,
                    week_end=MATCHUP_WEEK_END,
                )
            ]
        }
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(
        f"/api/leagues/{league.id}/adds", params={"as_of": MATCHUP_WEEK_START.isoformat()}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opponent_reason"] == "no_opponent_in_matchup"
    assert body["close_categories"] == []
    assert body["candidates"], "expected a need-only ranking, not an empty list, with no opponent"
    assert body["candidates"][0]["player_key"] == str(fa.id)


def test_adds_punt_zeroes_a_category(db_session):
    user = _seed_user(db_session)
    league, _team, _rival, stub = _seed_full_matchup(
        db_session, user, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    team_internal_id_by_abbr = _seed_matchup_schedule(db_session)
    helper = NbaPlayer(
        nba_person_id=962001, full_name="Multi Helper", position="C",
        nba_team_id=team_internal_id_by_abbr["DAL"],
    )  # fmt: skip
    db_session.add(helper)
    db_session.flush()
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=helper.id, season=get_settings().current_season, games_played=70,
            fgm=6.0, fga=11.0, ftm=2.0, fta=3.0, tpm=0.0, pts=14.0,
            reb=7.0, ast=1.5, stl=0.6, blk=1.5, tov=1.2,
        )
    )  # fmt: skip
    db_session.flush()
    client = _authed_client(db_session, user, stub)

    no_punt = client.get(
        f"/api/leagues/{league.id}/adds", params={"as_of": MATCHUP_WEEK_START.isoformat()}
    )
    punted = client.get(
        f"/api/leagues/{league.id}/adds",
        params={"as_of": MATCHUP_WEEK_START.isoformat(), "punt": "blk"},
    )

    assert no_punt.status_code == 200
    assert punted.status_code == 200
    no_punt_candidate = next(
        c for c in no_punt.json()["candidates"] if c["player_key"] == str(helper.id)
    )
    punted_candidate = next(
        c for c in punted.json()["candidates"] if c["player_key"] == str(helper.id)
    )

    assert "category:blk" in no_punt_candidate["reasons"]
    assert "category:blk" not in punted_candidate["reasons"]
    assert "blk" in no_punt_candidate["categories_helped"]
    assert "blk" not in punted_candidate["categories_helped"]
    # punting removes ONLY blk's weight -- every other category's
    # contribution is unchanged, so the score must strictly drop, never rise
    assert punted_candidate["score"] < no_punt_candidate["score"]


_ADDS_STREAM_NBA_TEAM_IDS = {
    "BOS": 1610612738, "LAL": 1610612747, "DEN": 1610612743,
    "OKC": 1610612760, "MIA": 1610612748, "DAL": 1610612742,
}  # fmt: skip
# (day offset, home, away) -- DEN gets exactly 1 game in the week, MIA
# exactly 4, everything else is unused filler to keep the fixture minimal
_ADDS_STREAM_GAMES = [
    (0, "BOS", "LAL"), (0, "DEN", "OKC"), (1, "MIA", "BOS"),
    (2, "MIA", "LAL"), (4, "MIA", "DAL"), (6, "MIA", "DAL"),
]  # fmt: skip


def _adds_stream_schedule_fetcher(base_date: date):
    def _fetch(season: str) -> list[dict]:
        rows = []
        for day_offset, home, away in _ADDS_STREAM_GAMES:
            game_date = base_date + timedelta(days=day_offset)
            rows.append(
                {
                    "game_id": f"adds-stream-{game_date.isoformat()}-{home}-{away}",
                    "game_date": game_date.isoformat(),
                    "home_team_id": _ADDS_STREAM_NBA_TEAM_IDS[home],
                    "home_team_name": home,
                    "home_team_abbreviation": home,
                    "away_team_id": _ADDS_STREAM_NBA_TEAM_IDS[away],
                    "away_team_name": away,
                    "away_team_abbreviation": away,
                }
            )
        return rows

    return _fetch


def _seed_adds_stream_fixture(db_session, user):
    """League + one rostered anchor (BOS, establishes real need weights)
    plus two free agents on a custom schedule: fa1 (DEN, exactly 1 game in
    the window, strong per-game rates) and fa2 (MIA, exactly 4 games, weaker
    per-game but engineered so its 4-game TOTAL dominates fa1's 1-game total
    in every single category, tov included -- guaranteed to outrank fa1 for
    ANY nonnegative category-weight vector, proving the schedule -> rank
    wiring end to end rather than asserting a hand-tuned coincidence.
    Returns (league, team, fa1, fa2, stub) with a single-team matchup (no
    opponent, close_categories always empty -- isolates the schedule/need
    wiring this fixture exists to prove)."""
    league, team, _rival = _seed_league_with_team(db_session, user)
    league.settings_json = {"max_weekly_adds": 3}
    db_session.flush()

    sync_schedule(
        db_session, season=get_settings().current_season,
        fetcher=_adds_stream_schedule_fetcher(MATCHUP_WEEK_START),
    )  # fmt: skip
    db_session.flush()
    teams = (
        db_session.execute(
            select(NbaTeam).where(NbaTeam.nba_team_id.in_(_ADDS_STREAM_NBA_TEAM_IDS.values()))
        )
        .scalars()
        .all()
    )
    nba_id_to_abbr = {v: k for k, v in _ADDS_STREAM_NBA_TEAM_IDS.items()}
    team_internal_id_by_abbr = {nba_id_to_abbr[t.nba_team_id]: t.id for t in teams}

    _seed_matchup_player(
        db_session, 963001, "Anchor", "SF", "BOS", team_internal_id_by_abbr, team,
        fgm=6.0, fga=13.0, ftm=2.0, fta=2.8, tpm=1.5, pts=15.5,
        reb=5.0, ast=3.5, stl=0.9, blk=0.6, tov=1.7,
    )  # fmt: skip

    fa1 = NbaPlayer(
        nba_person_id=963002, full_name="Better One Game", position="SG",
        nba_team_id=team_internal_id_by_abbr["DEN"],
    )  # fmt: skip
    db_session.add(fa1)
    db_session.flush()
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=fa1.id, season=get_settings().current_season, games_played=70,
            fgm=9.0, fga=16.0, ftm=5.0, fta=6.0, tpm=3.0, pts=26.0,
            reb=7.0, ast=6.0, stl=1.5, blk=1.0, tov=2.0,
        )
    )  # fmt: skip

    fa2 = NbaPlayer(
        nba_person_id=963003, full_name="Weaker Four Game", position="SF",
        nba_team_id=team_internal_id_by_abbr["MIA"],
    )  # fmt: skip
    db_session.add(fa2)
    db_session.flush()
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=fa2.id, season=get_settings().current_season, games_played=70,
            fgm=3.6, fga=6.4, ftm=2.0, fta=2.4, tpm=1.2, pts=10.4,
            reb=2.8, ast=2.4, stl=0.6, blk=0.4, tov=0.3,
        )
    )  # fmt: skip
    db_session.flush()

    stub = _StubYahooClient(
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=MATCHUP_WEEK,
                    teams=[MatchupTeam(team_key=TEAM_KEY, name="My Team", category_totals={})],
                    week_start=MATCHUP_WEEK_START,
                    week_end=MATCHUP_WEEK_END,
                )
            ]
        }
    )
    return league, team, fa1, fa2, stub


def test_adds_four_game_streamer_outranks_one_game_better_player(db_session):
    user = _seed_user(db_session)
    league, _team, fa1, fa2, stub = _seed_adds_stream_fixture(db_session, user)
    client = _authed_client(db_session, user, stub)

    response = client.get(
        f"/api/leagues/{league.id}/adds", params={"as_of": MATCHUP_WEEK_START.isoformat()}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["window_basis"] == "remaining"
    player_keys = [c["player_key"] for c in body["candidates"]]
    assert str(fa2.id) in player_keys
    assert str(fa1.id) in player_keys
    assert player_keys.index(str(fa2.id)) < player_keys.index(str(fa1.id)), (
        "the 4-game streamer must outrank the 1-game better player"
    )
    top = body["candidates"][0]
    assert top["player_key"] == str(fa2.id)
    assert top["games_remaining"] == 4.0
    assert "schedule_driven" in top["reasons"]


def test_adds_window_basis_full_week_when_as_of_after_week_end(db_session):
    user = _seed_user(db_session)
    league, _team, _fa1, _fa2, stub = _seed_adds_stream_fixture(db_session, user)
    client = _authed_client(db_session, user, stub)

    response = client.get(f"/api/leagues/{league.id}/adds", params={"as_of": "2026-01-01"})

    assert response.status_code == 200
    body = response.json()
    assert body["window_basis"] == "full_week"
    assert body["candidates"], "a week entirely in the past must still produce a usable list"


def test_adds_fan_plausibility_favors_blocks_need_over_zero_block_guard(db_session):
    """Mandatory per the plan: a guard-heavy roster's most pressing category
    weakness is blocks -- a strong-everywhere-but-blocks guard free agent
    must never outrank a modest big who actually helps the real need."""
    user = _seed_user(db_session)
    league, _team, _rival, _stub = _seed_full_matchup(
        db_session, user, week_start=MATCHUP_WEEK_START, week_end=MATCHUP_WEEK_END
    )
    team_internal_id_by_abbr = _seed_matchup_schedule(db_session)

    big_add = NbaPlayer(
        nba_person_id=964001, full_name="Big Add", position="C",
        nba_team_id=team_internal_id_by_abbr["DAL"],
    )  # fmt: skip
    db_session.add(big_add)
    db_session.flush()
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=big_add.id, season=get_settings().current_season, games_played=70,
            fgm=6.0, fga=10.0, ftm=2.0, fta=3.0, tpm=0.0, pts=14.0,
            reb=8.0, ast=1.0, stl=0.5, blk=2.0, tov=1.4,
        )
    )  # fmt: skip

    guard_no_d = NbaPlayer(
        nba_person_id=964002, full_name="Guard No D", position="SG",
        nba_team_id=team_internal_id_by_abbr["OKC"],
    )  # fmt: skip
    db_session.add(guard_no_d)
    db_session.flush()
    db_session.add(
        PlayerSeasonAverage(
            nba_player_id=guard_no_d.id, season=get_settings().current_season, games_played=70,
            fgm=7.0, fga=15.0, ftm=3.0, fta=4.0, tpm=2.8, pts=20.0,
            reb=2.5, ast=7.0, stl=1.1, blk=0.0, tov=1.0,
        )
    )  # fmt: skip
    db_session.flush()

    stub = _StubYahooClient(
        scoreboard_by_league={
            LEAGUE_KEY: [
                Matchup(
                    week=MATCHUP_WEEK,
                    teams=[MatchupTeam(team_key=TEAM_KEY, name="My Team", category_totals={})],
                    week_start=MATCHUP_WEEK_START,
                    week_end=MATCHUP_WEEK_END,
                )
            ]
        }
    )
    client = _authed_client(db_session, user, stub)

    response = client.get(
        f"/api/leagues/{league.id}/adds", params={"as_of": MATCHUP_WEEK_START.isoformat()}
    )

    assert response.status_code == 200
    body = response.json()
    candidates_by_key = {c["player_key"]: c for c in body["candidates"]}
    assert str(big_add.id) in candidates_by_key
    assert str(guard_no_d.id) in candidates_by_key
    assert "blk" in candidates_by_key[str(big_add.id)]["categories_helped"]
    assert "blk" not in candidates_by_key[str(guard_no_d.id)]["categories_helped"]
    assert body["candidates"][0]["player_key"] == str(big_add.id), (
        "a blocks-needy roster's top add must not be a guard who provides zero blocks"
    )


# --- GET /api/leagues/{league_id}/trades ---

# fgm/fga/ftm/fta/pts/tov held IDENTICAL across every player in both groups
# on purpose -- only tpm/ast/stl (guard identity) and reb/blk (big identity)
# vary, so fg_pct/ft_pct/pts/tov stay "average" on both sides and can never
# collide with roster_compare's collapse guard the way a fuller, more
# "realistic" but uncontrolled stat line did in an earlier draft of this
# fixture (verified empirically: this exact shape yields evaluated=25,
# truncated=True, kept=25 with max_package=2 default)
_TRADE_BASE_STATS = dict(fgm=6.0, fga=12.0, ftm=2.0, fta=2.5, pts=15.0, tov=1.5)
_TRADE_GUARD_STATS = [
    dict(_TRADE_BASE_STATS, tpm=2.60, ast=7.2, stl=1.35, reb=3.10, blk=0.10),
    dict(_TRADE_BASE_STATS, tpm=2.55, ast=7.1, stl=1.33, reb=3.05, blk=0.11),
    dict(_TRADE_BASE_STATS, tpm=2.50, ast=7.0, stl=1.30, reb=3.00, blk=0.12),
    dict(_TRADE_BASE_STATS, tpm=2.45, ast=6.9, stl=1.28, reb=2.95, blk=0.13),
    dict(_TRADE_BASE_STATS, tpm=2.40, ast=6.8, stl=1.25, reb=2.90, blk=0.14),
]  # fmt: skip
_TRADE_BIG_STATS = [
    dict(_TRADE_BASE_STATS, tpm=0.0, ast=1.14, stl=0.43, reb=10.30, blk=2.15),
    dict(_TRADE_BASE_STATS, tpm=0.0, ast=1.10, stl=0.42, reb=10.20, blk=2.10),
    dict(_TRADE_BASE_STATS, tpm=0.0, ast=1.05, stl=0.41, reb=10.10, blk=2.05),
    dict(_TRADE_BASE_STATS, tpm=0.0, ast=1.00, stl=0.40, reb=10.00, blk=2.00),
    dict(_TRADE_BASE_STATS, tpm=0.0, ast=0.95, stl=0.39, reb=9.90, blk=1.95),
]  # fmt: skip


def _seed_trade_depth_rosters(db_session, user, *, user_is_guard: bool = True):
    """5 guards (genuine ast/tpm/stl surplus, reb/blk deficit) vs 5 bigs (the
    reverse) -- deep enough on both sides that a 1-for-1 or 2-for-2 swap
    never collapses a strong category (roster_compare's fragility guard would
    otherwise reject nearly every candidate on a 3-player roster, which is
    too shallow for this fixture's purpose). fg_pct/ft_pct/pts/tov are held
    near-identical across every player so those categories stay "average"
    for both sides and never collide with the collapse guard. Assigns the
    authed user's team via `user_is_guard`. Returns (league, my_team,
    other_team, guard_ids, big_ids).
    """
    league, team_row, rival_row = _seed_league_with_team(db_session, user)
    # team_row always hosts the guard roster and rival_row always hosts the
    # big roster -- only WHICH physical row is claimed by the authed user
    # changes, via user_id (a Team's roster is just its RosterSlot rows, so
    # swapping the claim is independent of who gets which players)
    guard_team, big_team = team_row, rival_row
    if not user_is_guard:
        # _seed_league_with_team always claims team_row (the guard roster
        # here) for the authed user -- move the claim to rival_row (the big
        # roster) so "mine" resolves to the big-heavy side instead
        team_row.user_id = None
        rival_row.user_id = user.id
        db_session.flush()

    guard_ids = []
    for i, stats in enumerate(_TRADE_GUARD_STATS, start=1):
        person_id = 970100 + i
        p = NbaPlayer(nba_person_id=person_id, full_name=f"Guard {i}", position="PG")
        db_session.add(p)
        db_session.flush()
        db_session.add(
            PlayerSeasonAverage(
                nba_player_id=p.id, season=get_settings().current_season, games_played=70, **stats
            )
        )
        key = f"{LEAGUE_KEY}.p.{person_id}"
        db_session.add(
            PlayerIdMap(nba_player_id=p.id, yahoo_player_key=key, yahoo_name=p.full_name, match_method="exact")
        )
        db_session.add(
            RosterSlot(
                team_id=guard_team.id, yahoo_player_key=key, player_name=p.full_name,
                position="PG", injury_status=None,
            )
        )
        guard_ids.append(p.id)

    big_ids = []
    for i, stats in enumerate(_TRADE_BIG_STATS, start=1):
        person_id = 970200 + i
        p = NbaPlayer(nba_person_id=person_id, full_name=f"Big {i}", position="C")
        db_session.add(p)
        db_session.flush()
        db_session.add(
            PlayerSeasonAverage(
                nba_player_id=p.id, season=get_settings().current_season, games_played=70, **stats
            )
        )
        key = f"{LEAGUE_KEY}.p.{person_id}"
        db_session.add(
            PlayerIdMap(nba_player_id=p.id, yahoo_player_key=key, yahoo_name=p.full_name, match_method="exact")
        )
        db_session.add(
            RosterSlot(
                team_id=big_team.id, yahoo_player_key=key, player_name=p.full_name,
                position="C", injury_status=None,
            )
        )
        big_ids.append(p.id)
    db_session.flush()

    my_team = team_row if user_is_guard else rival_row
    other_team = rival_row if user_is_guard else team_row
    return league, my_team, other_team, guard_ids, big_ids


def test_trades_404_for_foreign_league(db_session):
    user = _seed_user(db_session, guid="guid-a", name="A")
    other = _seed_user(db_session, guid="guid-b", name="B")
    league, _team, _rival = _seed_league_with_team(db_session, other)

    client = _authed_client(db_session, user)
    response = client.get(f"/api/leagues/{league.id}/trades", params={"team_id": 1})

    assert response.status_code == 404


def test_trades_same_team_rejected(db_session):
    user = _seed_user(db_session)
    league, my_team, _other, _guard_ids, _big_ids = _seed_trade_depth_rosters(db_session, user)
    client = _authed_client(db_session, user)

    response = client.get(f"/api/leagues/{league.id}/trades", params={"team_id": my_team.id})

    assert response.status_code == 400


def test_trades_team_from_another_league_rejected(db_session):
    user = _seed_user(db_session)
    league, _my_team, _other, _guard_ids, _big_ids = _seed_trade_depth_rosters(db_session, user)

    other_user = _seed_user(db_session, guid="guid-other-league", name="Other")
    other_league = League(
        yahoo_league_key="466.l.999", name="Another League", season=2026, num_teams=2,
        scoring_type="head", settings_json={},
    )
    db_session.add(other_league)
    db_session.flush()
    foreign_team = Team(
        league_id=other_league.id, yahoo_team_key="466.l.999.t.1", name="Foreign Team",
        is_users_team=True, user_id=other_user.id,
    )
    db_session.add(foreign_team)
    db_session.flush()

    client = _authed_client(db_session, user)
    # a real team_id, but scoped to a DIFFERENT league -- must never be
    # comparable through this league's route, even though the row exists
    response = client.get(f"/api/leagues/{league.id}/trades", params={"team_id": foreign_team.id})

    assert response.status_code == 404


def test_trades_shape_evaluated_truncated_and_downside(db_session):
    user = _seed_user(db_session)
    league, my_team, other_team, _guard_ids, _big_ids = _seed_trade_depth_rosters(db_session, user)
    client = _authed_client(db_session, user)

    response = client.get(f"/api/leagues/{league.id}/trades", params={"team_id": other_team.id})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "mine", "theirs", "players", "verdicts", "evaluated", "truncated", "value_basis", "stale", "synced_at",
    }  # fmt: skip
    assert body["value_basis"] == "category_impact_only"
    assert set(body["mine"].keys()) == {"team_id", "categories", "surplus", "deficit"}
    assert body["mine"]["team_id"] == my_team.id
    assert body["theirs"]["team_id"] == other_team.id
    assert set(body["mine"]["categories"].keys()) == NINE_CATEGORIES
    strength = body["mine"]["categories"]["ast"]
    assert set(strength.keys()) == {
        "category", "total", "mean", "label", "depth", "fragile", "top_contributor", "top_share",
    }  # fmt: skip
    assert "ast" in body["mine"]["surplus"]
    assert "reb" in body["mine"]["deficit"]
    assert "reb" in body["theirs"]["surplus"]
    assert "ast" in body["theirs"]["deficit"]

    # a 5-deep roster on both sides with max_package=2 (default) generates
    # well over the internal generation cap -- proves truncation is
    # surfaced, per the plan's "never silently truncate" rule
    assert body["evaluated"] > 0
    assert body["truncated"] is True
    assert len(body["verdicts"]) > 0

    verdict = body["verdicts"][0]
    assert set(verdict.keys()) == {"give", "get", "mine", "theirs", "net_value", "verdict", "reasons"}
    assert set(verdict["mine"].keys()) == {"before", "after", "gained", "lost", "collapsed"}
    assert set(verdict["mine"]["before"].keys()) == {"totals", "labels", "means"}
    for key in [*verdict["give"], *verdict["get"]]:
        assert key in body["players"]
        assert set(body["players"][key].keys()) == {"name", "position", "nba_person_id", "headshot_url"}

    # named downside, mandatory per plan T4: every real trade makes
    # something worse -- giving up a top ast/tpm/stl contributor for a
    # rebounder necessarily costs mine roster in the categories it gave up
    assert any(r.startswith("lost:") for r in verdict["reasons"])


def test_trades_never_proposes_a_center_deep_team_giving_up_a_guard(db_session):
    """Mandatory per the plan: a team deep at center and thin at guard is
    never told to give up a guard for a center. The authed user's team IS
    the big-heavy roster here (user_is_guard=False) -- its give-eligible
    pool can only ever be centers (there are no ast/tpm-surplus guards on
    this roster to offer), so every verdict's give side must be centers."""
    user = _seed_user(db_session)
    league, _my_team, other_team, guard_ids, big_ids = _seed_trade_depth_rosters(
        db_session, user, user_is_guard=False
    )
    client = _authed_client(db_session, user)

    response = client.get(f"/api/leagues/{league.id}/trades", params={"team_id": other_team.id})

    assert response.status_code == 200
    body = response.json()
    assert "reb" in body["mine"]["surplus"]
    assert "blk" in body["mine"]["surplus"]
    assert "ast" in body["mine"]["deficit"]

    guard_keys = {f"{LEAGUE_KEY}.p.{970100 + i}" for i in range(1, 6)}
    big_keys = {f"{LEAGUE_KEY}.p.{970200 + i}" for i in range(1, 6)}
    assert body["verdicts"], "expected real candidates from a genuinely deep-on-both-sides fixture"
    for verdict in body["verdicts"]:
        assert set(verdict["give"]) <= big_keys, "a center-deep team must never be offered up giving a guard"
        assert set(verdict["get"]) <= guard_keys
