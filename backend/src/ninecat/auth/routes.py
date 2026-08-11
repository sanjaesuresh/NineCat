"""Yahoo OAuth2 login/callback/logout routes.

Login and logout live under /api; the callback intentionally does not, because its
path must exactly match https://localhost:8000/auth/yahoo/callback as registered
with Yahoo -- /api/auth/yahoo/callback would not match the registered redirect URI.
"""

import secrets
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ninecat.auth.crypto import encrypt_token
from ninecat.auth.sessions import SESSION_COOKIE_NAME, set_session_on_response
from ninecat.config import get_settings
from ninecat.db import get_session
from ninecat.models import User, YahooToken

router = APIRouter()

YAHOO_AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
STATE_MAX_AGE_SECONDS = 10 * 60
HTTP_TIMEOUT_SECONDS = 10.0

# short-lived, unsigned cookie holding the raw nonce; see the double-submit comment
# in yahoo_login for why this exists alongside the signed state param
OAUTH_NONCE_COOKIE_NAME = "ninecat_oauth_nonce"

# separate salt from the session-cookie serializer (ninecat.auth.sessions) so a
# leaked/replayed oauth state value can never double as a valid session cookie
_STATE_SALT = "ninecat-oauth-state"


def _state_serializer() -> URLSafeTimedSerializer:
    # built fresh per call (not module-cached), matching sessions._serializer(), so
    # tests that monkeypatch session_secret + clear get_settings' cache take effect
    return URLSafeTimedSerializer(get_settings().session_secret, salt=_STATE_SALT)


def get_http_client() -> Generator[httpx.Client, None, None]:
    """FastAPI dependency yielding the httpx client used for the Yahoo token exchange.

    Kept as a Depends()-injected factory (not a module-level client) so tests can
    swap in a client backed by httpx.MockTransport via
    app.dependency_overrides[get_http_client], without touching the network.
    """
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        yield client


def _auth_error_redirect(frontend_origin: str) -> RedirectResponse:
    response = RedirectResponse(
        url=f"{frontend_origin}/?auth_error=1", status_code=status.HTTP_302_FOUND
    )
    # the nonce is single-use regardless of outcome -- clear it so a stale cookie
    # can't linger and be reused (or confuse) a later login attempt
    response.delete_cookie(
        key=OAUTH_NONCE_COOKIE_NAME, httponly=True, secure=True, samesite="lax"
    )
    return response


@router.get("/api/auth/yahoo/login")
def yahoo_login() -> RedirectResponse:
    settings = get_settings()
    # itsdangerous alone only proves *we* issued this state -- it does not prove the
    # browser presenting it at the callback is the same one that started this login.
    # an attacker can start their own login, capture a validly-signed state+code pair,
    # and hand that URL to a victim, whose browser would then complete the callback
    # and get logged into the attacker's account. binding a random nonce into both the
    # signed state AND a same-site httpOnly cookie (double-submit) closes that: the
    # callback only succeeds if both the signature AND the cookie (which an attacker
    # cannot set on the victim's browser) agree on the same nonce.
    nonce = secrets.token_urlsafe(32)
    state = _state_serializer().dumps(nonce)
    authorize_url = httpx.URL(
        YAHOO_AUTHORIZE_URL,
        params={
            "client_id": settings.yahoo_client_id,
            "redirect_uri": settings.yahoo_redirect_uri,
            "response_type": "code",
            "state": state,
        },
    )
    response = RedirectResponse(url=str(authorize_url), status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=OAUTH_NONCE_COOKIE_NAME,
        value=nonce,
        max_age=STATE_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get("/auth/yahoo/callback")
def yahoo_callback(
    request: Request,
    db: Session = Depends(get_session),
    http_client: httpx.Client = Depends(get_http_client),
) -> RedirectResponse:
    settings = get_settings()

    # covers the user denying consent on Yahoo's screen (?error=access_denied) and a
    # missing code/state, before the state signature is even checked
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if request.query_params.get("error") or not code or not state:
        return _auth_error_redirect(settings.frontend_origin)

    try:
        state_nonce = _state_serializer().loads(state, max_age=STATE_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return _auth_error_redirect(settings.frontend_origin)

    # double-submit check: the signed state's nonce must match the nonce this same
    # browser was handed at /login -- a forged/replayed state from another browser
    # has no way to also supply the matching httpOnly cookie
    cookie_nonce = request.cookies.get(OAUTH_NONCE_COOKIE_NAME)
    if cookie_nonce is None or cookie_nonce != state_nonce:
        return _auth_error_redirect(settings.frontend_origin)

    try:
        token_response = http_client.post(
            YAHOO_TOKEN_URL,
            data={
                "client_id": settings.yahoo_client_id,
                "client_secret": settings.yahoo_client_secret,
                "redirect_uri": settings.yahoo_redirect_uri,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
    except httpx.HTTPError:
        # network/timeout talking to Yahoo -- never let the exception (which could
        # echo request data, e.g. client_secret in a connection error) reach a response
        return _auth_error_redirect(settings.frontend_origin)

    if token_response.status_code != status.HTTP_200_OK:
        return _auth_error_redirect(settings.frontend_origin)

    try:
        payload = token_response.json()
        refresh_token: str = payload["refresh_token"]
        expires_in = payload["expires_in"]
        yahoo_guid: str = payload["xoauth_yahoo_guid"]
        # timedelta raises TypeError (not ValueError) for a non-numeric seconds
        # value, e.g. Yahoo sending expires_in as a JSON string -- must stay
        # inside this try, and TypeError must stay in the except tuple below,
        # or a malformed-but-200 response escapes as an unhandled 500 instead
        # of the same auth_error redirect every other bad-payload case gets
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    except (ValueError, KeyError, TypeError):
        return _auth_error_redirect(settings.frontend_origin)

    user = db.execute(select(User).where(User.yahoo_guid == yahoo_guid)).scalar_one_or_none()
    if user is None:
        # no extra profile call in this task -- live enrichment of display_name
        # comes later, so every newly-created user starts with this placeholder
        user = User(yahoo_guid=yahoo_guid, display_name="Yahoo User")
        db.add(user)
        db.flush()
    elif user.deleted_at is not None:
        # yahoo_guid is unique, so a soft-deleted row already reserves this guid --
        # reactivate it in place instead of inserting, which would hit that constraint
        user.deleted_at = None

    encrypted_refresh_token = encrypt_token(refresh_token)
    token_row = db.execute(
        select(YahooToken).where(YahooToken.user_id == user.id)
    ).scalar_one_or_none()
    if token_row is None:
        token_row = YahooToken(
            user_id=user.id,
            encrypted_refresh_token=encrypted_refresh_token,
            access_token_expires_at=expires_at,
        )
        db.add(token_row)
    else:
        token_row.encrypted_refresh_token = encrypted_refresh_token
        token_row.access_token_expires_at = expires_at

    db.flush()

    response = RedirectResponse(
        url=f"{settings.frontend_origin}/dashboard", status_code=status.HTTP_302_FOUND
    )
    set_session_on_response(response, user.id)
    # nonce is single-use: clear it now that the login it protected has completed
    response.delete_cookie(
        key=OAUTH_NONCE_COOKIE_NAME, httponly=True, secure=True, samesite="lax"
    )
    return response


@router.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    # attributes must match what set_session_on_response set at login, or the
    # browser treats this as a different cookie and won't actually delete it
    response.delete_cookie(key=SESSION_COOKIE_NAME, httponly=True, secure=True, samesite="lax")
    return response
