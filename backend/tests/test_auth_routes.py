import dataclasses
import json
from collections.abc import Generator
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from ninecat.auth.crypto import decrypt_token
from ninecat.auth.routes import (
    DEV_LEAGUE_KEY,
    DEV_LEAGUE_SETTINGS_JSON,
    DEV_USER_GUID,
    OAUTH_NONCE_COOKIE_NAME,
    YAHOO_AUTHORIZE_URL,
    _DEV_PLAYERS,
    _DEV_POOL_PLAYERS,
    get_http_client,
    router,
)
from ninecat.auth.sessions import SESSION_COOKIE_NAME, verify_session_cookie
from ninecat.config import get_settings
from ninecat.db import get_session
from ninecat.models import (
    League,
    NbaPlayer,
    PlayerIdMap,
    PlayerProjection,
    PlayerSeasonAverage,
    RosterSlot,
    Team,
    User,
    YahooApiCache,
    YahooToken,
)
from ninecat.yahoo.gateway import _path_hash
from ninecat.yahoo.parsers import parse_league_settings

# total NbaPlayer/PlayerIdMap/PlayerSeasonAverage rows a dev-login seeds: the
# 3 rostered dev players plus the unrostered draftable pool
_TOTAL_DEV_PLAYERS = len(_DEV_PLAYERS) + len(_DEV_POOL_PLAYERS)

_YAHOO_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "yahoo"

FAKE_TOKEN_PAYLOAD = {
    # regression fixture: yahoo's real token response has NO xoauth_yahoo_guid key
    # (live-verified keys=['access_token','expires_in','refresh_token','token_type']) --
    # the guid now only ever comes from the separate FAKE_USERS_PAYLOAD fetch below
    "access_token": "fake-access-token",
    "refresh_token": "fake-refresh-token-plaintext",
    "expires_in": 3600,
    "token_type": "bearer",
}

# shape of a real GET .../users;use_login=1?format=json body: user is wrapped
# under a "0" key, and its attributes arrive as a list of single-key dicts that
# must be merged (same yahoo quirk yahoo/parsers.py's _merge_attrs handles)
FAKE_USERS_PAYLOAD = {
    "fantasy_content": {
        "users": {
            "0": {"user": [[{"guid": "yahoo-guid-1"}]]},
            "count": 1,
        }
    }
}


@pytest.fixture(autouse=True)
def _real_session_secret(monkeypatch: pytest.MonkeyPatch):
    # conftest's dummy SESSION_SECRET works for itsdangerous (any string is valid),
    # but pin an explicit one so these tests don't depend on that shared dummy value
    monkeypatch.setenv("SESSION_SECRET", "a-real-looking-session-secret-value")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _real_fernet_key(monkeypatch: pytest.MonkeyPatch):
    # conftest's dummy TOKEN_ENCRYPTION_KEY isn't a valid Fernet key (not base64/32
    # bytes); the callback encrypts a real refresh token so it needs a real one
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client(app: FastAPI) -> TestClient:
    # base_url must be https: set_session_on_response/the oauth nonce cookie are both
    # secure=True, and a client whose base_url is plain http (TestClient's default)
    # silently drops secure cookies instead of carrying them to the next request --
    # this must match the real deployment (https://localhost:8000) or the double-submit
    # nonce cookie from /login would never make it to /auth/yahoo/callback in tests
    return TestClient(app, base_url="https://testserver")


def _app(db_session, token_handler=None) -> FastAPI:
    """Build a real app with the auth router mounted, db + http client overridden."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: db_session

    if token_handler is not None:

        def _override_http_client() -> Generator[httpx.Client, None, None]:
            with httpx.Client(transport=httpx.MockTransport(token_handler)) as client:
                yield client

        app.dependency_overrides[get_http_client] = _override_http_client

    return app


def _ok_token_handler(request: httpx.Request) -> httpx.Response:
    # the callback now makes two calls: POST .../get_token, then GET
    # .../users;use_login=1 for the guid -- route on path so both are served
    # by this one MockTransport handler
    if request.url.path == "/oauth2/get_token":
        return httpx.Response(200, json=FAKE_TOKEN_PAYLOAD)
    return httpx.Response(200, json=FAKE_USERS_PAYLOAD)


def _yahoo_error_handler(request: httpx.Request) -> httpx.Response:
    # token exchange itself fails here, so the callback returns before ever
    # reaching the guid fetch -- no need to branch on path
    return httpx.Response(400, json={"error": "invalid_grant"})


def _guid_fetch_error_handler(request: httpx.Request) -> httpx.Response:
    # token exchange succeeds, but the follow-up guid fetch 500s -- pins the
    # new failure mode this task adds
    if request.url.path == "/oauth2/get_token":
        return httpx.Response(200, json=FAKE_TOKEN_PAYLOAD)
    return httpx.Response(500, json={"error": "server_error"})


def _row_count(session, model) -> int:
    # snapshot a table's total row count around an action -- lets "writes nothing"
    # assertions hold even when the shared dev database already has committed rows
    # from an unrelated e2e run (this suite's db_session only rolls back ITS OWN
    # writes, it can't roll back what a prior process already committed)
    return len(session.execute(select(model)).scalars().all())


def _login_state(client: TestClient) -> str:
    """Hit the real login endpoint to mint a validly-signed state value."""
    response = client.get("/api/auth/yahoo/login", follow_redirects=False)
    location = response.headers["location"]
    query = parse_qs(urlsplit(location).query)
    return query["state"][0]


# --- GET /api/auth/yahoo/login ---


def test_login_redirects_to_yahoo_with_state(db_session):
    client = _client(_app(db_session))

    response = client.get("/api/auth/yahoo/login", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(YAHOO_AUTHORIZE_URL)
    query = parse_qs(urlsplit(location).query)
    assert "state" in query
    assert query["response_type"] == ["code"]

    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    assert cookie[OAUTH_NONCE_COOKIE_NAME].value != ""


# --- GET /auth/yahoo/callback: happy path ---


def test_callback_happy_path_creates_user_and_encrypted_token(db_session):
    client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(client)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/dashboard"

    # two Set-Cookie headers land here: the new session cookie and the nonce
    # cookie being cleared -- collect both into one jar rather than relying on
    # response.headers["set-cookie"], which only returns the first match
    cookie = SimpleCookie()
    for raw_cookie in response.headers.get_list("set-cookie"):
        cookie.load(raw_cookie)
    morsel = cookie[SESSION_COOKIE_NAME]
    session_user_id = verify_session_cookie(morsel.value)
    assert session_user_id is not None

    user = db_session.execute(
        select(User).where(User.yahoo_guid == "yahoo-guid-1")
    ).scalar_one()
    assert user.id == session_user_id
    assert user.display_name == "Yahoo User"
    assert user.deleted_at is None

    token_row = db_session.execute(
        select(YahooToken).where(YahooToken.user_id == user.id)
    ).scalar_one()
    assert token_row.encrypted_refresh_token != "fake-refresh-token-plaintext"
    assert decrypt_token(token_row.encrypted_refresh_token) == "fake-refresh-token-plaintext"
    assert token_row.access_token_expires_at > datetime.now(timezone.utc)


# --- GET /auth/yahoo/callback: failures ---


def test_callback_bad_state_redirects_with_auth_error_and_changes_nothing(db_session):
    client = _client(_app(db_session, token_handler=_ok_token_handler))
    users_before = _row_count(db_session, User)
    tokens_before = _row_count(db_session, YahooToken)

    response = client.get(
        "/auth/yahoo/callback?code=fake-code&state=not-a-real-state", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    # no session cookie on failure -- the only Set-Cookie here (if any) is the
    # error-path nonce cleanup, never a signed-in session
    assert SESSION_COOKIE_NAME not in response.cookies
    assert _row_count(db_session, User) == users_before
    assert _row_count(db_session, YahooToken) == tokens_before


def test_callback_expired_state_redirects_with_auth_error(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    from ninecat.auth.routes import STATE_MAX_AGE_SECONDS

    fake_now = [1_700_000_000.0]
    monkeypatch.setattr("time.time", lambda: fake_now[0])

    client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(client)
    fake_now[0] += STATE_MAX_AGE_SECONDS + 1
    users_before = _row_count(db_session, User)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert _row_count(db_session, User) == users_before


def test_callback_yahoo_error_response_redirects_with_auth_error(db_session):
    client = _client(_app(db_session, token_handler=_yahoo_error_handler))
    state = _login_state(client)
    users_before = _row_count(db_session, User)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert _row_count(db_session, User) == users_before


def test_callback_guid_fetch_failure_redirects_with_auth_error_and_writes_nothing(db_session):
    # regression: token exchange succeeding is not enough on its own anymore --
    # a failed follow-up guid fetch must still land on auth_error with no DB writes,
    # same as every other failure mode in this callback
    client = _client(_app(db_session, token_handler=_guid_fetch_error_handler))
    state = _login_state(client)
    users_before = _row_count(db_session, User)
    tokens_before = _row_count(db_session, YahooToken)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert SESSION_COOKIE_NAME not in response.cookies
    assert _row_count(db_session, User) == users_before
    assert _row_count(db_session, YahooToken) == tokens_before


def test_callback_missing_code_redirects_with_auth_error(db_session):
    client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(client)
    users_before = _row_count(db_session, User)

    response = client.get(f"/auth/yahoo/callback?state={state}", follow_redirects=False)

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert _row_count(db_session, User) == users_before


def test_callback_yahoo_denied_consent_redirects_with_auth_error(db_session):
    client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(client)

    response = client.get(
        f"/auth/yahoo/callback?state={state}&error=access_denied", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"


# --- GET /auth/yahoo/callback: double-submit nonce (CSRF) ---


def test_callback_missing_nonce_cookie_redirects_with_auth_error(db_session):
    # mint a validly-signed state via one client (which also receives the nonce
    # cookie), then present that same state from a fresh client with no cookies --
    # simulates an attacker handing a victim a captured login URL
    minting_client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(minting_client)

    victim_client = _client(_app(db_session, token_handler=_ok_token_handler))
    users_before = _row_count(db_session, User)
    tokens_before = _row_count(db_session, YahooToken)
    response = victim_client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert _row_count(db_session, User) == users_before
    assert _row_count(db_session, YahooToken) == tokens_before


def test_callback_mismatched_nonce_cookie_redirects_with_auth_error(db_session):
    client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(client)
    # tamper with the nonce cookie the login step just set, so it no longer
    # matches the nonce signed into state
    client.cookies.set(OAUTH_NONCE_COOKIE_NAME, "a-different-nonce-value")
    users_before = _row_count(db_session, User)
    tokens_before = _row_count(db_session, YahooToken)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert _row_count(db_session, User) == users_before
    assert _row_count(db_session, YahooToken) == tokens_before


# --- GET /auth/yahoo/callback: malformed token payload ---


def test_callback_expires_in_as_string_redirects_with_auth_error(db_session):
    # regression: timedelta(seconds=<str>) raises TypeError, not ValueError/KeyError --
    # a 200 response with a non-numeric expires_in must not escape as an unhandled 500
    def handler(request: httpx.Request) -> httpx.Response:
        payload = dict(FAKE_TOKEN_PAYLOAD, expires_in="3600")
        return httpx.Response(200, json=payload)

    client = _client(_app(db_session, token_handler=handler))
    state = _login_state(client)
    users_before = _row_count(db_session, User)
    tokens_before = _row_count(db_session, YahooToken)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert _row_count(db_session, User) == users_before
    assert _row_count(db_session, YahooToken) == tokens_before


def test_callback_non_dict_json_body_redirects_with_auth_error(db_session):
    # a JSON array (or any non-dict) makes payload["refresh_token"] raise TypeError,
    # not KeyError -- must be caught the same way as a missing/malformed field
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["unexpected", "array", "body"])

    client = _client(_app(db_session, token_handler=handler))
    state = _login_state(client)
    users_before = _row_count(db_session, User)
    tokens_before = _row_count(db_session, YahooToken)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert _row_count(db_session, User) == users_before
    assert _row_count(db_session, YahooToken) == tokens_before


# --- GET /auth/yahoo/callback: reactivation ---


def test_callback_reactivates_soft_deleted_user_instead_of_inserting(db_session):
    existing = User(
        yahoo_guid="yahoo-guid-1",
        display_name="Old Name",
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(existing)
    db_session.flush()
    existing_id = existing.id

    client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(client)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/dashboard"

    users = db_session.execute(
        select(User).where(User.yahoo_guid == "yahoo-guid-1")
    ).scalars().all()
    assert len(users) == 1
    assert users[0].id == existing_id
    assert users[0].deleted_at is None


# --- POST /api/auth/logout ---


def test_logout_clears_cookie_and_returns_204(db_session):
    client = _client(_app(db_session))
    client.cookies.set(SESSION_COOKIE_NAME, "some-cookie-value")

    response = client.post("/api/auth/logout")

    assert response.status_code == 204
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    morsel = cookie[SESSION_COOKIE_NAME]
    assert morsel.value == ""
    assert int(morsel["max-age"]) <= 0


# --- POST /api/auth/dev-login ---


def test_dev_login_404_when_flag_disabled(db_session, monkeypatch: pytest.MonkeyPatch):
    # explicit, not ambient: don't rely on whatever DEV_AUTH_ENABLED happens to
    # be in the local .env/process env -- pin it false so this test means what it says
    monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
    get_settings.cache_clear()
    client = _client(_app(db_session))
    users_before = _row_count(db_session, User)
    leagues_before = _row_count(db_session, League)

    response = client.post("/api/auth/dev-login")

    assert response.status_code == 404
    assert _row_count(db_session, User) == users_before
    assert _row_count(db_session, League) == leagues_before


def test_dev_login_seeds_dataset_and_sets_session_cookie(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = _client(_app(db_session))

    response = client.post("/api/auth/dev-login")

    assert response.status_code == 204
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    session_user_id = verify_session_cookie(cookie[SESSION_COOKIE_NAME].value)
    assert session_user_id is not None

    user = db_session.execute(
        select(User).where(User.yahoo_guid == DEV_USER_GUID)
    ).scalar_one()
    assert user.id == session_user_id
    assert user.display_name == "Dev User"

    league = db_session.execute(
        select(League).where(League.yahoo_league_key == DEV_LEAGUE_KEY)
    ).scalar_one()
    teams = db_session.execute(select(Team).where(Team.league_id == league.id)).scalars().all()
    assert len(teams) == 2
    dev_team = next(t for t in teams if t.is_users_team)
    assert dev_team.user_id == user.id

    # settings_json must match what parsing a REAL Yahoo settings response produces
    # (not just the DEV_LEAGUE_SETTINGS_JSON constant against itself, which would
    # pass even if that constant silently drifted from the real fixture) --
    # roster_positions/max_weekly_adds/playoff fields differ in this real fixture,
    # but categories/roster_positions shape and stat_ids/is_negative must match
    real_settings_raw = json.loads((_YAHOO_FIXTURE_DIR / "league_settings.json").read_text())
    real_settings_json = dataclasses.asdict(parse_league_settings(real_settings_raw))
    assert real_settings_json["categories"] == league.settings_json["categories"]
    assert real_settings_json["roster_positions"] == league.settings_json["roster_positions"]
    assert real_settings_json["max_weekly_adds"] == league.settings_json["max_weekly_adds"]
    assert real_settings_json["playoff_start_week"] == league.settings_json["playoff_start_week"]
    assert real_settings_json["num_playoff_teams"] == league.settings_json["num_playoff_teams"]
    assert len(league.settings_json["roster_positions"]) == 10
    assert len(league.settings_json["categories"]) == 9
    assert {c["stat_id"] for c in league.settings_json["categories"]} == {
        5, 8, 10, 12, 15, 16, 17, 18, 19,
    }
    turnovers = next(c for c in league.settings_json["categories"] if c["stat_id"] == 19)
    assert turnovers["is_negative"] is True

    roster = (
        db_session.execute(select(RosterSlot).where(RosterSlot.team_id == dev_team.id))
        .scalars()
        .all()
    )
    assert {slot.player_name for slot in roster} == {
        "Dev Player One",
        "Dev Player Two",
        "Dev Player Three",
    }
    injured = next(s for s in roster if s.player_name == "Dev Player Two")
    assert injured.injury_status == "INJ"
    healthy = next(s for s in roster if s.player_name == "Dev Player One")
    assert healthy.injury_status is None

    assert len(db_session.execute(select(NbaPlayer)).scalars().all()) == _TOTAL_DEV_PLAYERS
    assert len(db_session.execute(select(PlayerIdMap)).scalars().all()) == _TOTAL_DEV_PLAYERS
    season_avgs = db_session.execute(select(PlayerSeasonAverage)).scalars().all()
    assert len(season_avgs) == _TOTAL_DEV_PLAYERS
    assert all(avg.season == get_settings().current_season for avg in season_avgs)
    # the 3 fixed roster players keep their original hardcoded games_played=70;
    # the pool's per-player games vary, so only assert on the rostered subset
    rostered_ids = {
        p.id
        for p in db_session.execute(
            select(NbaPlayer).where(
                NbaPlayer.nba_person_id.in_([spec["person_id"] for spec in _DEV_PLAYERS])
            )
        )
        .scalars()
        .all()
    }
    assert all(avg.games_played == 70 for avg in season_avgs if avg.nba_player_id in rostered_ids)


def test_dev_login_seeds_draftable_pool_unrostered_with_projections(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = _client(_app(db_session))

    client.post("/api/auth/dev-login")

    pool_person_ids = [spec["person_id"] for spec in _DEV_POOL_PLAYERS]
    pool_players = (
        db_session.execute(
            select(NbaPlayer).where(NbaPlayer.nba_person_id.in_(pool_person_ids))
        )
        .scalars()
        .all()
    )
    assert len(pool_players) == len(_DEV_POOL_PLAYERS)
    # unrostered: none of the pool player ids show up as a RosterSlot player_key
    pool_keys = {f"{DEV_LEAGUE_KEY}.p.{pid}" for pid in pool_person_ids}
    rostered_keys = {
        slot.yahoo_player_key for slot in db_session.execute(select(RosterSlot)).scalars().all()
    }
    assert pool_keys.isdisjoint(rostered_keys)
    # every pool player has a position (draft-engine scarcity depends on it)
    assert all(p.position for p in pool_players)

    pool_ids_internal = {p.id for p in pool_players}
    projections = (
        db_session.execute(
            select(PlayerProjection).where(PlayerProjection.nba_player_id.in_(pool_ids_internal))
        )
        .scalars()
        .all()
    )
    assert len(projections) == len(_DEV_POOL_PLAYERS)
    assert all(proj.source == "dev-seed" for proj in projections)
    assert all(proj.season == get_settings().current_season for proj in projections)
    # the 45-60 games_played/projected_games band represents this pool's
    # injury-risk archetype -- there must be a handful, not zero and not most
    low_games = [proj for proj in projections if 45 <= proj.projected_games <= 60]
    assert 6 <= len(low_games) <= 10

    season_avgs = (
        db_session.execute(
            select(PlayerSeasonAverage).where(
                PlayerSeasonAverage.nba_player_id.in_(pool_ids_internal)
            )
        )
        .scalars()
        .all()
    )
    assert len(season_avgs) == len(_DEV_POOL_PLAYERS)


def test_dev_login_pool_stats_are_internally_consistent(db_session, monkeypatch: pytest.MonkeyPatch):
    # guards against hand-entered stat lines drifting out of sync with each
    # other (e.g. fgm > fga, or a pts total that doesn't match makes) -- the
    # draft engine trusts these numbers at face value, so bad rows must fail
    # loudly here rather than silently skew valuation in the demo
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = _client(_app(db_session))

    client.post("/api/auth/dev-login")

    rows = db_session.execute(select(PlayerSeasonAverage)).scalars().all() + list(
        db_session.execute(select(PlayerProjection)).scalars().all()
    )
    assert len(rows) > 0
    for row in rows:
        assert row.fga >= row.fgm, row.nba_player_id
        assert row.fta >= row.ftm, row.nba_player_id
        # threes made can never exceed total field goals made -- the most
        # likely hand-entry error in a stat line like this
        assert row.tpm <= row.fgm, row.nba_player_id
        expected_pts = 2 * (row.fgm - row.tpm) + 3 * row.tpm + row.ftm
        assert abs(row.pts - expected_pts) <= 1.0, (row.nba_player_id, row.pts, expected_pts)


def test_dev_login_heals_drifted_pool_rows(db_session, monkeypatch: pytest.MonkeyPatch):
    # a row seeded before a seed constant changed (or before the position
    # column existed) must not carry stale data forever -- get-or-create only
    # writes on insert, so re-login has to actively reconcile drifted rows,
    # same as it already does for League.settings_json
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = _client(_app(db_session))
    client.post("/api/auth/dev-login")

    spec = _DEV_POOL_PLAYERS[0]
    nba_player = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == spec["person_id"])
    ).scalar_one()
    # simulate a pre-existing dev row seeded before position existed, plus a
    # hand-entry stat mistake that later got fixed in the seed constant
    nba_player.position = None
    season_avg = db_session.execute(
        select(PlayerSeasonAverage).where(PlayerSeasonAverage.nba_player_id == nba_player.id)
    ).scalar_one()
    season_avg.games_played = 1
    season_avg.pts = 0.1
    projection = db_session.execute(
        select(PlayerProjection).where(
            PlayerProjection.nba_player_id == nba_player.id, PlayerProjection.source == "dev-seed"
        )
    ).scalar_one()
    projection.projected_games = 1
    projection.pts = 0.1
    db_session.flush()

    client.post("/api/auth/dev-login")
    db_session.expire_all()

    healed_player = db_session.get(NbaPlayer, nba_player.id)
    assert healed_player.position == spec["position"]
    healed_avg = db_session.get(PlayerSeasonAverage, season_avg.id)
    assert healed_avg.games_played == spec["games"]
    assert healed_avg.pts == spec["averages"]["pts"]
    healed_projection = db_session.get(PlayerProjection, projection.id)
    assert healed_projection.projected_games == spec["games"]
    assert healed_projection.pts == spec["averages"]["pts"]


def test_dev_login_is_idempotent(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = _client(_app(db_session))

    first = client.post("/api/auth/dev-login")
    second = client.post("/api/auth/dev-login")

    assert first.status_code == 204
    assert second.status_code == 204
    assert len(db_session.execute(select(User).where(User.yahoo_guid == DEV_USER_GUID)).scalars().all()) == 1
    league = db_session.execute(
        select(League).where(League.yahoo_league_key == DEV_LEAGUE_KEY)
    ).scalar_one()
    assert len(db_session.execute(select(Team).where(Team.league_id == league.id)).scalars().all()) == 2
    assert len(db_session.execute(select(RosterSlot)).scalars().all()) == 3
    assert len(db_session.execute(select(NbaPlayer)).scalars().all()) == _TOTAL_DEV_PLAYERS
    assert len(db_session.execute(select(PlayerIdMap)).scalars().all()) == _TOTAL_DEV_PLAYERS
    assert len(db_session.execute(select(PlayerSeasonAverage)).scalars().all()) == _TOTAL_DEV_PLAYERS
    assert len(db_session.execute(select(PlayerProjection)).scalars().all()) == len(_DEV_POOL_PLAYERS)
    assert league.settings_json == DEV_LEAGUE_SETTINGS_JSON


def test_dev_login_warms_scoreboard_cache_with_gateways_own_path_hash(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    # regression: this must use the gateway's real _path_hash, not a local
    # reimplementation of the same sha256 scheme, or a future change to that
    # scheme would silently desync the two and dev-login would 401 again
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    client = _client(_app(db_session))

    client.post("/api/auth/dev-login")

    user = db_session.execute(select(User).where(User.yahoo_guid == DEV_USER_GUID)).scalar_one()
    expected_hash = _path_hash(f"league/{DEV_LEAGUE_KEY}/scoreboard")
    cache_row = db_session.execute(
        select(YahooApiCache).where(
            YahooApiCache.user_id == user.id, YahooApiCache.path_hash == expected_hash
        )
    ).scalar_one()
    first_fetched_at = cache_row.fetched_at

    # a second dev-login must re-upsert (bump fetched_at), not leave a stale
    # cache row behind -- that's what keeps the overview call's cache hit fresh
    client.post("/api/auth/dev-login")
    db_session.expire(cache_row)
    assert cache_row.fetched_at > first_fetched_at
