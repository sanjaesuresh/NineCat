"""Single choke point for every Yahoo Fantasy API call the app makes.

No other module is permitted to call fantasysports.yahooapis.com directly --
everything (caching, token refresh, retry/backoff) funnels through
YahooGateway so those concerns are enforced in exactly one place.
"""

import hashlib
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.auth.crypto import decrypt_token, encrypt_token
from ninecat.config import get_settings
from ninecat.models.cache import YahooApiCache
from ninecat.models.core import YahooToken

YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_FANTASY_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
HTTP_TIMEOUT_SECONDS = 10.0
# refresh preemptively once the access token is this close to expiring, so a
# resource call is never sent alongside a token that dies mid-flight
TOKEN_REFRESH_MARGIN_SECONDS = 60
MAX_RESOURCE_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5


class YahooUnavailableError(Exception):
    """Raised when Yahoo is unreachable/erroring after retries.

    Carries whatever cached payload exists (regardless of its age) so a caller
    can serve stale data with a "may be out of date" banner instead of failing.
    """

    def __init__(self, stale_payload: dict | None, synced_at: datetime | None):
        super().__init__("Yahoo Fantasy API unavailable after retries")
        self.stale_payload = stale_payload
        self.synced_at = synced_at


class YahooAuthError(Exception):
    """Raised when Yahoo rejects our stored refresh token.

    Callers map this to a re-auth flow. The stored token is intentionally left
    alone here -- deleting it is a decision for the caller, not the gateway.
    """


class _YahooRequestFailed(Exception):
    """Internal signal that the resource-fetch loop gave up; never escapes get()."""


def _backoff_delay(attempt: int) -> float:
    # exponential backoff plus jitter so many gateways retrying at once don't
    # all hammer Yahoo again in lockstep
    return _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, _BACKOFF_BASE_SECONDS)


class YahooGateway:
    """Caches, authenticates, and retries Yahoo Fantasy API requests for one user."""

    def __init__(self, session: Session, user_id: int, http_client: httpx.Client | None = None):
        self._session = session
        self._user_id = user_id
        self._http_client = http_client or httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
        # access tokens are never persisted (only the encrypted refresh token
        # is); each gateway instance starts with none in memory and refreshes
        # lazily on first use, so one refresh per instance lifetime is normal
        self._access_token: str | None = None
        self._access_token_expires_at: datetime | None = None

    def get(self, resource_path: str, cache_ttl_seconds: int) -> dict:
        """Return parsed JSON for resource_path, serving a fresh cache row if one exists."""
        path_hash = _path_hash(resource_path)
        cached = self._get_cache_row(path_hash)
        if cached is not None and _is_fresh(cached.fetched_at, cache_ttl_seconds):
            return cached.payload

        # token refresh must happen before the resource call, not as part of
        # the retry loop below, so a near-expiry token never gets used at all
        self._ensure_access_token()

        try:
            payload = self._fetch_with_retry(resource_path)
        except _YahooRequestFailed:
            stale_payload = cached.payload if cached is not None else None
            synced_at = cached.fetched_at if cached is not None else None
            raise YahooUnavailableError(stale_payload=stale_payload, synced_at=synced_at)

        self._upsert_cache(path_hash, payload)
        return payload

    def record_fixture(self, resource_path: str, dest_dir: str | Path) -> Path:
        """Dev-only: perform one live GET and save the response as a fixture file.

        Bypasses the cache entirely -- fixtures are meant to capture a real
        Yahoo response for the test suite, not to be served back by get().
        """
        self._ensure_access_token()
        response = self._request(resource_path)
        response.raise_for_status()
        payload = response.json()

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        file_path = dest / f"{_sanitize_filename(resource_path)}.json"
        file_path.write_text(json.dumps(payload, indent=2))
        return file_path

    # --- token refresh ---

    def _ensure_access_token(self) -> None:
        now = datetime.now(timezone.utc)
        needs_refresh = (
            self._access_token is None
            or self._access_token_expires_at is None
            or self._access_token_expires_at - now <= timedelta(seconds=TOKEN_REFRESH_MARGIN_SECONDS)
        )
        if needs_refresh:
            self._refresh_access_token()

    def _refresh_access_token(self) -> None:
        # lock the row for the duration of this refresh so two concurrent
        # refreshes can't both read the same soon-to-be-stale refresh token
        # and race to overwrite each other's rotation
        token_row = self._session.execute(
            select(YahooToken).where(YahooToken.user_id == self._user_id).with_for_update()
        ).scalar_one_or_none()
        if token_row is None:
            raise YahooAuthError("no stored Yahoo token for this user")

        refresh_token = decrypt_token(token_row.encrypted_refresh_token)
        settings = get_settings()
        try:
            response = self._http_client.post(
                YAHOO_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": settings.yahoo_client_id,
                    "client_secret": settings.yahoo_client_secret,
                    "refresh_token": refresh_token,
                },
            )
        except httpx.HTTPError:
            # swallow rather than chain (`from exc`): the underlying httpx exception's
            # .request carries the refresh_token in its POST body, and chaining would
            # let that reach a traceback/log downstream
            raise YahooAuthError("network error refreshing Yahoo token") from None

        if response.status_code != 200:
            raise YahooAuthError("Yahoo rejected the stored refresh token")

        try:
            payload = response.json()
            new_access_token: str = payload["access_token"]
            # yahoo may or may not rotate the refresh token on a given refresh --
            # fall back to the current one so we always persist a valid value
            new_refresh_token: str = payload.get("refresh_token", refresh_token)
            expires_in = payload["expires_in"]
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        except (ValueError, KeyError, TypeError) as exc:
            raise YahooAuthError("malformed response from Yahoo token endpoint") from exc

        token_row.encrypted_refresh_token = encrypt_token(new_refresh_token)
        token_row.access_token_expires_at = expires_at
        self._session.flush()
        # yahoo consumed the old token; rotation must survive any later request
        # failure -- intentional mid-request commit
        self._session.commit()

        self._access_token = new_access_token
        self._access_token_expires_at = expires_at

    # --- resource fetch with 401-retry and 429/5xx backoff ---

    def _fetch_with_retry(self, resource_path: str) -> dict:
        attempts = 0
        refreshed_for_401 = False
        while True:
            try:
                response = self._request(resource_path)
            except httpx.HTTPError:
                # network failure (timeout, connection error, ...) is retried exactly
                # like a 5xx -- Yahoo being unreachable and Yahoo erroring both end up
                # needing the same stale-payload-or-fail outcome from the caller
                attempts += 1
                if attempts >= MAX_RESOURCE_ATTEMPTS:
                    raise _YahooRequestFailed("network error after retries") from None
                time.sleep(_backoff_delay(attempts))
                continue

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise _YahooRequestFailed("non-JSON 200 response") from exc

            if response.status_code == 401 and not refreshed_for_401:
                # one-shot: refresh and retry immediately, doesn't consume the
                # 429/5xx backoff budget below
                refreshed_for_401 = True
                self._refresh_access_token()
                continue

            if response.status_code == 429 or response.status_code >= 500:
                attempts += 1
                if attempts >= MAX_RESOURCE_ATTEMPTS:
                    raise _YahooRequestFailed(f"status {response.status_code} after retries")
                time.sleep(_backoff_delay(attempts))
                continue

            # any other status (including a second 401) is not retryable here
            raise _YahooRequestFailed(f"status {response.status_code}")

    def _request(self, resource_path: str) -> httpx.Response:
        url = httpx.URL(
            f"{YAHOO_FANTASY_API_BASE}/{resource_path.lstrip('/')}", params={"format": "json"}
        )
        headers = {"Authorization": f"Bearer {self._access_token}"}
        return self._http_client.get(url, headers=headers)

    # --- cache table ---

    def _get_cache_row(self, path_hash: str) -> YahooApiCache | None:
        return self._session.execute(
            select(YahooApiCache).where(
                YahooApiCache.user_id == self._user_id, YahooApiCache.path_hash == path_hash
            )
        ).scalar_one_or_none()

    def _upsert_cache(self, path_hash: str, payload: dict) -> None:
        now = datetime.now(timezone.utc)
        # atomic upsert: a select-then-insert here would let two concurrent
        # cold-cache fetches for the same path both insert and trip the unique
        # constraint -- ON CONFLICT makes the second writer update in place instead
        stmt = pg_insert(YahooApiCache).values(
            user_id=self._user_id, path_hash=path_hash, payload=payload, fetched_at=now
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "path_hash"],
            set_={"payload": stmt.excluded.payload, "fetched_at": stmt.excluded.fetched_at},
        )
        self._session.execute(stmt)
        self._session.flush()


def _path_hash(resource_path: str) -> str:
    return hashlib.sha256(resource_path.encode()).hexdigest()


def _is_fresh(fetched_at: datetime, cache_ttl_seconds: int) -> bool:
    return fetched_at + timedelta(seconds=cache_ttl_seconds) > datetime.now(timezone.utc)


def _sanitize_filename(resource_path: str) -> str:
    # fixture filenames are derived only from the (public) resource path, never
    # from token material, and must be safe to use as a single path segment
    return re.sub(r"[^A-Za-z0-9._-]", "_", resource_path.strip("/"))
