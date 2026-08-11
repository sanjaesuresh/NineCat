import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from ninecat.auth.crypto import decrypt_token, encrypt_token
from ninecat.config import get_settings
from ninecat.models import User, YahooToken
from ninecat.models.cache import YahooApiCache
from ninecat.yahoo.gateway import (
    YAHOO_FANTASY_API_BASE,
    YAHOO_TOKEN_URL,
    YahooAuthError,
    YahooGateway,
    YahooUnavailableError,
)

FAKE_REFRESH_TOKEN = "fake-refresh-token-plaintext"
FAKE_ACCESS_TOKEN = "fake-access-token"


@pytest.fixture(autouse=True)
def _real_fernet_key(monkeypatch: pytest.MonkeyPatch):
    # conftest's dummy TOKEN_ENCRYPTION_KEY isn't a valid Fernet key; these tests
    # encrypt/decrypt real refresh tokens so they need a real one
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_user_with_token(db_session, expires_at: datetime | None = None) -> User:
    user = User(yahoo_guid="guid-1", display_name="Test User")
    db_session.add(user)
    db_session.flush()
    token = YahooToken(
        user_id=user.id,
        encrypted_refresh_token=encrypt_token(FAKE_REFRESH_TOKEN),
        access_token_expires_at=expires_at
        or (datetime.now(timezone.utc) + timedelta(hours=1)),
    )
    db_session.add(token)
    db_session.flush()
    return user


def _refresh_response(
    refresh_token: str = FAKE_REFRESH_TOKEN, access_token: str = FAKE_ACCESS_TOKEN
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": 3600,
        },
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _path_hash(resource_path: str) -> str:
    return hashlib.sha256(resource_path.encode()).hexdigest()


def _add_cache_row(db_session, user_id: int, resource_path: str, payload: dict, fetched_at: datetime):
    row = YahooApiCache(
        user_id=user_id, path_hash=_path_hash(resource_path), payload=payload, fetched_at=fetched_at
    )
    db_session.add(row)
    db_session.flush()
    return row


# --- fresh cache hit ---


def test_fresh_cache_hit_makes_zero_network_calls(db_session):
    user = _make_user_with_token(db_session)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    _add_cache_row(
        db_session, user.id, "league/123", {"ok": True}, datetime.now(timezone.utc)
    )

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))
    result = gateway.get("league/123", cache_ttl_seconds=3600)

    assert result == {"ok": True}
    assert calls == []


# --- expired access token refreshes before the resource call ---


def test_expired_access_token_refreshes_before_resource_call(db_session):
    user = _make_user_with_token(
        db_session, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    call_order = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(YAHOO_TOKEN_URL):
            call_order.append("refresh")
            return _refresh_response()
        call_order.append("resource")
        return httpx.Response(200, json={"data": 1})

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))
    result = gateway.get("league/123", cache_ttl_seconds=3600)

    assert call_order == ["refresh", "resource"]
    assert result == {"data": 1}


# --- 401-then-success ---


def test_401_then_success_refreshes_once_and_retries(db_session):
    # a gateway instance always refreshes once on its first call (no access
    # token is held in memory yet) -- warm it up on a separate path first so
    # the assertions below isolate only the 401-triggered refresh/retry
    user = _make_user_with_token(db_session)
    refresh_calls = []
    league_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(YAHOO_TOKEN_URL):
            refresh_calls.append(request)
            return _refresh_response()
        if url.startswith(f"{YAHOO_FANTASY_API_BASE}/warmup"):
            return httpx.Response(200, json={"warmup": True})
        league_calls.append(request)
        if len(league_calls) == 1:
            return httpx.Response(401, json={"error": "token_expired"})
        return httpx.Response(200, json={"data": 2})

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))
    gateway.get("warmup", cache_ttl_seconds=3600)
    refresh_calls.clear()

    result = gateway.get("league/123", cache_ttl_seconds=3600)

    assert result == {"data": 2}
    assert len(refresh_calls) == 1
    assert len(league_calls) == 2

    cached = db_session.execute(
        select(YahooApiCache).where(
            YahooApiCache.user_id == user.id,
            YahooApiCache.path_hash == _path_hash("league/123"),
        )
    ).scalar_one()
    assert cached.payload == {"data": 2}


# --- three 5xx -> YahooUnavailableError with stale payload ---


def test_three_5xx_raises_unavailable_with_stale_payload(db_session, monkeypatch):
    sleeps = []
    monkeypatch.setattr("ninecat.yahoo.gateway.time.sleep", lambda s: sleeps.append(s))

    user = _make_user_with_token(db_session)
    old_fetched_at = datetime.now(timezone.utc) - timedelta(days=1)
    _add_cache_row(db_session, user.id, "league/123", {"stale": True}, old_fetched_at)

    resource_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(YAHOO_TOKEN_URL):
            return _refresh_response()
        resource_calls.append(request)
        return httpx.Response(500)

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))

    with pytest.raises(YahooUnavailableError) as exc_info:
        gateway.get("league/123", cache_ttl_seconds=1)

    assert exc_info.value.stale_payload == {"stale": True}
    assert exc_info.value.synced_at == old_fetched_at
    assert len(resource_calls) == 3
    assert len(sleeps) == 2


# --- transport-level network errors retry like 5xx and still surface stale data ---


def test_network_error_three_times_raises_unavailable_with_stale_payload(db_session, monkeypatch):
    sleeps = []
    monkeypatch.setattr("ninecat.yahoo.gateway.time.sleep", lambda s: sleeps.append(s))

    user = _make_user_with_token(db_session)
    old_fetched_at = datetime.now(timezone.utc) - timedelta(days=1)
    _add_cache_row(db_session, user.id, "league/123", {"stale": True}, old_fetched_at)

    resource_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(YAHOO_TOKEN_URL):
            return _refresh_response()
        resource_calls.append(request)
        raise httpx.ConnectError("connection refused")

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))

    with pytest.raises(YahooUnavailableError) as exc_info:
        gateway.get("league/123", cache_ttl_seconds=1)

    assert exc_info.value.stale_payload == {"stale": True}
    assert exc_info.value.synced_at == old_fetched_at
    assert len(resource_calls) == 3
    assert len(sleeps) == 2


# --- refresh rejection -> YahooAuthError, token left untouched ---


def test_refresh_rejection_raises_auth_error_and_keeps_token(db_session):
    user = _make_user_with_token(
        db_session, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    original_encrypted = (
        db_session.execute(select(YahooToken).where(YahooToken.user_id == user.id))
        .scalar_one()
        .encrypted_refresh_token
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))

    with pytest.raises(YahooAuthError):
        gateway.get("league/123", cache_ttl_seconds=3600)

    token_row = db_session.execute(
        select(YahooToken).where(YahooToken.user_id == user.id)
    ).scalar_one()
    assert token_row.encrypted_refresh_token == original_encrypted


# --- rotated refresh token persisted encrypted ---


def test_rotated_refresh_token_persisted_encrypted(db_session):
    user = _make_user_with_token(
        db_session, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(YAHOO_TOKEN_URL):
            return _refresh_response(refresh_token="rotated-refresh-token")
        return httpx.Response(200, json={"ok": True})

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))
    gateway.get("league/123", cache_ttl_seconds=3600)

    token_row = db_session.execute(
        select(YahooToken).where(YahooToken.user_id == user.id)
    ).scalar_one()
    assert token_row.encrypted_refresh_token != "rotated-refresh-token"
    assert decrypt_token(token_row.encrypted_refresh_token) == "rotated-refresh-token"


# --- rotation is committed immediately, not left pending on the outer transaction ---


def test_refresh_commits_immediately_after_rotation(db_session, monkeypatch):
    user = _make_user_with_token(
        db_session, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    commit_calls = []
    original_commit = db_session.commit
    monkeypatch.setattr(
        db_session, "commit", lambda: (commit_calls.append(True), original_commit())[-1]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(YAHOO_TOKEN_URL):
            return _refresh_response(refresh_token="rotated-refresh-token")
        return httpx.Response(200, json={"ok": True})

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))
    gateway.get("league/123", cache_ttl_seconds=3600)

    assert len(commit_calls) == 1


# --- cache upsert idempotent ---


def test_cache_upsert_idempotent_updates_same_row(db_session):
    user = _make_user_with_token(db_session)
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(YAHOO_TOKEN_URL):
            return _refresh_response()
        call_count[0] += 1
        return httpx.Response(200, json={"n": call_count[0]})

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))
    gateway.get("league/123", cache_ttl_seconds=0)
    gateway.get("league/123", cache_ttl_seconds=0)

    rows = (
        db_session.execute(select(YahooApiCache).where(YahooApiCache.user_id == user.id))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].payload == {"n": 2}


# --- record_fixture ---


def test_record_fixture_writes_json_file(db_session, tmp_path):
    user = _make_user_with_token(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(YAHOO_TOKEN_URL):
            return _refresh_response()
        return httpx.Response(200, json={"fixture": True})

    gateway = YahooGateway(db_session, user.id, http_client=_client(handler))
    file_path = gateway.record_fixture("league/123/standings", tmp_path)

    assert file_path.exists()
    assert file_path.parent == tmp_path
    assert json.loads(file_path.read_text()) == {"fixture": True}
    assert "league_123_standings" in file_path.name
    # never derived from token material
    assert FAKE_ACCESS_TOKEN not in file_path.name
