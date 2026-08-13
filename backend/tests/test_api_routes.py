import math
from collections import Counter
from datetime import datetime, timedelta, timezone
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
    PlayerIdMap,
    PlayerProjection,
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
