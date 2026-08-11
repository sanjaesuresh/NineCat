from datetime import datetime, timezone
from http.cookies import SimpleCookie

import pytest
from fastapi import Depends, FastAPI, Response
from fastapi.testclient import TestClient

from ninecat.auth.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_session_cookie,
    current_user,
    set_session_on_response,
    verify_session_cookie,
)
from ninecat.config import get_settings
from ninecat.db import get_session
from ninecat.models import User


@pytest.fixture(autouse=True)
def _real_session_secret(monkeypatch: pytest.MonkeyPatch):
    # conftest's dummy SESSION_SECRET works fine for itsdangerous (any string is a valid
    # secret), but pin an explicit one here so these tests don't depend on that dummy value
    monkeypatch.setenv("SESSION_SECRET", "a-real-looking-session-secret-value")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _protected_app(session_override=None) -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    def protected(user: User = Depends(current_user)):
        return {"user_id": user.id}

    if session_override is not None:
        app.dependency_overrides[get_session] = lambda: session_override
    return app


# --- create_session_cookie / verify_session_cookie ---


def test_round_trip_returns_user_id():
    cookie = create_session_cookie(42)
    assert verify_session_cookie(cookie) == 42


def test_tampered_cookie_returns_none():
    cookie = create_session_cookie(42)
    tampered = cookie[:-2] + ("aa" if cookie[-2:] != "aa" else "bb")
    assert verify_session_cookie(tampered) is None


def test_garbage_cookie_returns_none():
    assert verify_session_cookie("not-a-real-cookie") is None


def test_expired_cookie_returns_none(monkeypatch: pytest.MonkeyPatch):
    # itsdangerous reads time.time() at sign and verify time; fast-forward the clock past
    # the 30-day expiry rather than actually waiting 30 days
    fake_now = [1_700_000_000.0]
    monkeypatch.setattr("time.time", lambda: fake_now[0])
    cookie = create_session_cookie(7)
    fake_now[0] += SESSION_MAX_AGE_SECONDS + 1
    assert verify_session_cookie(cookie) is None


# --- set_session_on_response ---


def test_set_session_on_response_sets_expected_cookie_attributes():
    response = Response()
    set_session_on_response(response, 99)

    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    morsel = cookie[SESSION_COOKIE_NAME]

    assert morsel["httponly"]
    assert morsel["secure"]
    assert morsel["samesite"].lower() == "lax"
    assert morsel["max-age"] == str(SESSION_MAX_AGE_SECONDS)
    assert verify_session_cookie(morsel.value) == 99


# --- current_user dependency ---


def test_current_user_raises_401_with_no_cookie():
    client = TestClient(_protected_app())
    response = client.get("/protected")
    assert response.status_code == 401


def test_current_user_raises_401_with_tampered_cookie():
    client = TestClient(_protected_app())
    response = client.get("/protected", cookies={SESSION_COOKIE_NAME: "garbage"})
    assert response.status_code == 401


def test_current_user_returns_user_for_valid_cookie(db_session):
    user = User(yahoo_guid="guid-current-user-1", display_name="Test User")
    db_session.add(user)
    db_session.flush()

    client = TestClient(_protected_app(session_override=db_session))
    cookie = create_session_cookie(user.id)
    response = client.get("/protected", cookies={SESSION_COOKIE_NAME: cookie})
    assert response.status_code == 200
    assert response.json() == {"user_id": user.id}


def test_current_user_raises_401_for_unknown_user_id(db_session):
    client = TestClient(_protected_app(session_override=db_session))
    cookie = create_session_cookie(999_999_999)
    response = client.get("/protected", cookies={SESSION_COOKIE_NAME: cookie})
    assert response.status_code == 401


def test_current_user_raises_401_for_deleted_user(db_session):
    user = User(
        yahoo_guid="guid-deleted-user-1",
        display_name="Deleted User",
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    client = TestClient(_protected_app(session_override=db_session))
    cookie = create_session_cookie(user.id)
    response = client.get("/protected", cookies={SESSION_COOKIE_NAME: cookie})
    assert response.status_code == 401
