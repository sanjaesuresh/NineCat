from collections.abc import Generator
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from ninecat.auth.crypto import decrypt_token
from ninecat.auth.routes import (
    OAUTH_NONCE_COOKIE_NAME,
    YAHOO_AUTHORIZE_URL,
    get_http_client,
    router,
)
from ninecat.auth.sessions import SESSION_COOKIE_NAME, verify_session_cookie
from ninecat.config import get_settings
from ninecat.db import get_session
from ninecat.models import User, YahooToken

FAKE_TOKEN_PAYLOAD = {
    "access_token": "fake-access-token",
    "refresh_token": "fake-refresh-token-plaintext",
    "expires_in": 3600,
    "xoauth_yahoo_guid": "yahoo-guid-1",
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
    return httpx.Response(200, json=FAKE_TOKEN_PAYLOAD)


def _yahoo_error_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(400, json={"error": "invalid_grant"})


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

    response = client.get(
        "/auth/yahoo/callback?code=fake-code&state=not-a-real-state", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    # no session cookie on failure -- the only Set-Cookie here (if any) is the
    # error-path nonce cleanup, never a signed-in session
    assert SESSION_COOKIE_NAME not in response.cookies
    assert db_session.execute(select(User)).scalars().all() == []
    assert db_session.execute(select(YahooToken)).scalars().all() == []


def test_callback_expired_state_redirects_with_auth_error(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    from ninecat.auth.routes import STATE_MAX_AGE_SECONDS

    fake_now = [1_700_000_000.0]
    monkeypatch.setattr("time.time", lambda: fake_now[0])

    client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(client)
    fake_now[0] += STATE_MAX_AGE_SECONDS + 1

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert db_session.execute(select(User)).scalars().all() == []


def test_callback_yahoo_error_response_redirects_with_auth_error(db_session):
    client = _client(_app(db_session, token_handler=_yahoo_error_handler))
    state = _login_state(client)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert db_session.execute(select(User)).scalars().all() == []


def test_callback_missing_code_redirects_with_auth_error(db_session):
    client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(client)

    response = client.get(f"/auth/yahoo/callback?state={state}", follow_redirects=False)

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert db_session.execute(select(User)).scalars().all() == []


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
    response = victim_client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert db_session.execute(select(User)).scalars().all() == []
    assert db_session.execute(select(YahooToken)).scalars().all() == []


def test_callback_mismatched_nonce_cookie_redirects_with_auth_error(db_session):
    client = _client(_app(db_session, token_handler=_ok_token_handler))
    state = _login_state(client)
    # tamper with the nonce cookie the login step just set, so it no longer
    # matches the nonce signed into state
    client.cookies.set(OAUTH_NONCE_COOKIE_NAME, "a-different-nonce-value")

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert db_session.execute(select(User)).scalars().all() == []
    assert db_session.execute(select(YahooToken)).scalars().all() == []


# --- GET /auth/yahoo/callback: malformed token payload ---


def test_callback_expires_in_as_string_redirects_with_auth_error(db_session):
    # regression: timedelta(seconds=<str>) raises TypeError, not ValueError/KeyError --
    # a 200 response with a non-numeric expires_in must not escape as an unhandled 500
    def handler(request: httpx.Request) -> httpx.Response:
        payload = dict(FAKE_TOKEN_PAYLOAD, expires_in="3600")
        return httpx.Response(200, json=payload)

    client = _client(_app(db_session, token_handler=handler))
    state = _login_state(client)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert db_session.execute(select(User)).scalars().all() == []
    assert db_session.execute(select(YahooToken)).scalars().all() == []


def test_callback_non_dict_json_body_redirects_with_auth_error(db_session):
    # a JSON array (or any non-dict) makes payload["refresh_token"] raise TypeError,
    # not KeyError -- must be caught the same way as a missing/malformed field
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["unexpected", "array", "body"])

    client = _client(_app(db_session, token_handler=handler))
    state = _login_state(client)

    response = client.get(
        f"/auth/yahoo/callback?code=fake-code&state={state}", follow_redirects=False
    )

    frontend_origin = get_settings().frontend_origin
    assert response.status_code == 302
    assert response.headers["location"] == f"{frontend_origin}/?auth_error=1"
    assert db_session.execute(select(User)).scalars().all() == []
    assert db_session.execute(select(YahooToken)).scalars().all() == []


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
