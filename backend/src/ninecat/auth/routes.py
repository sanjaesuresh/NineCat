"""Yahoo OAuth2 login/callback/logout routes.

Login and logout live under /api; the callback intentionally does not, because its
path must exactly match https://localhost:8000/auth/yahoo/callback as registered
with Yahoo -- /api/auth/yahoo/callback would not match the registered redirect URI.
"""

import logging
import secrets
from collections.abc import Generator
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.auth.crypto import encrypt_token
from ninecat.auth.sessions import SESSION_COOKIE_NAME, set_session_on_response
from ninecat.config import get_settings
from ninecat.db import get_session
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
    YahooApiCache,
    YahooToken,
)
# reuse the gateway's own hash scheme (not a local reimplementation) so this
# cache-warm can never drift out of sync with what YahooGateway.get() actually
# looks up -- if the hash algorithm or path template ever changes there, this
# breaks loudly (ImportError / wrong-hash test failure) instead of silently
from ninecat.yahoo.gateway import _path_hash
# reuse the real parser dataclasses (not a hand-rolled dict) so the dev
# league's settings_json is byte-for-byte the same shape sync_league_detail
# produces from a live Yahoo response -- the draft engine can't tell the
# difference between dev-seeded and real settings
from ninecat.yahoo.parsers import CategoryInfo, LeagueSettings, RosterPosition

router = APIRouter()

# reason tags only -- never token material, values, or query params
logger = logging.getLogger(__name__)

YAHOO_AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
# live-verified (2026-08): yahoo's real token response omits xoauth_yahoo_guid
# entirely (payload keys are just access_token/expires_in/refresh_token/token_type),
# so the guid has to be fetched separately via this fantasy API call, using the
# access_token from the exchange above
YAHOO_USERS_URL = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1"
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


def _auth_error_redirect(frontend_origin: str, reason: str = "unspecified") -> RedirectResponse:
    logger.warning("yahoo callback rejected: %s", reason)
    response = RedirectResponse(
        url=f"{frontend_origin}/?auth_error=1", status_code=status.HTTP_302_FOUND
    )
    # the nonce is single-use regardless of outcome -- clear it so a stale cookie
    # can't linger and be reused (or confuse) a later login attempt
    response.delete_cookie(
        key=OAUTH_NONCE_COOKIE_NAME, httponly=True, secure=True, samesite="lax"
    )
    return response


def _extract_yahoo_guid(payload: dict) -> str:
    """Pull the logged-in user's guid out of a /users;use_login=1?format=json body.

    Mirrors the tolerance in yahoo/parsers.py's _merge_attrs: yahoo wraps the
    single user under a "0" key, and that user's attributes arrive as EITHER a
    plain dict OR a list of single-key dicts that must be merged -- accept both
    rather than assuming one, same as every other yahoo response shape in this
    codebase. Any KeyError/TypeError/IndexError here is a parse miss and must be
    caught by the caller, not allowed to become an unhandled 500.
    """
    users = payload["fantasy_content"]["users"]
    user_wrap = users["0"] if isinstance(users, dict) else users[0]
    user = user_wrap["user"]
    attrs = user[0]
    if isinstance(attrs, list):
        merged: dict = {}
        for item in attrs:
            merged.update(item)
        attrs = merged
    return attrs["guid"]


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
            # fspt-r = fantasy sports read; request it explicitly -- tokens minted
            # without it get 403 from fantasysports.yahooapis.com (live-observed)
            "scope": "fspt-r",
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
        return _auth_error_redirect(settings.frontend_origin, "denied_or_missing_params")

    try:
        state_nonce = _state_serializer().loads(state, max_age=STATE_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return _auth_error_redirect(settings.frontend_origin, "bad_or_expired_state")

    # double-submit check: the signed state's nonce must match the nonce this same
    # browser was handed at /login -- a forged/replayed state from another browser
    # has no way to also supply the matching httpOnly cookie
    cookie_nonce = request.cookies.get(OAUTH_NONCE_COOKIE_NAME)
    if cookie_nonce is None or cookie_nonce != state_nonce:
        return _auth_error_redirect(
            settings.frontend_origin,
            "nonce_cookie_missing" if cookie_nonce is None else "nonce_mismatch",
        )

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
    except httpx.HTTPError as exc:
        # network/timeout talking to Yahoo -- never let the exception (which could
        # echo request data, e.g. client_secret in a connection error) reach a response
        return _auth_error_redirect(
            settings.frontend_origin, f"token_exchange_{type(exc).__name__}"
        )

    if token_response.status_code != status.HTTP_200_OK:
        return _auth_error_redirect(
            settings.frontend_origin, f"token_exchange_status_{token_response.status_code}"
        )

    try:
        payload = token_response.json()
        access_token: str = payload["access_token"]
        refresh_token: str = payload["refresh_token"]
        expires_in = payload["expires_in"]
        # timedelta raises TypeError (not ValueError) for a non-numeric seconds
        # value, e.g. Yahoo sending expires_in as a JSON string -- must stay
        # inside this try, and TypeError must stay in the except tuple below,
        # or a malformed-but-200 response escapes as an unhandled 500 instead
        # of the same auth_error redirect every other bad-payload case gets
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    except (ValueError, KeyError, TypeError) as exc:
        # key NAMES present in the payload are safe to log; values never are
        try:
            present = sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
        except Exception:
            present = "unparseable"
        return _auth_error_redirect(
            settings.frontend_origin,
            f"token_payload_invalid ({type(exc).__name__}); keys={present}",
        )

    # yahoo's real token response doesn't include the guid (see YAHOO_USERS_URL
    # comment above) -- fetch it now via the fantasy API, using the same injected
    # http_client so this call is mockable in tests exactly like the token exchange
    try:
        users_response = http_client.get(
            YAHOO_USERS_URL,
            params={"format": "json"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except httpx.HTTPError as exc:
        # never let the exception reach a response -- it could echo the access
        # token (e.g. in a connection error's request repr)
        return _auth_error_redirect(settings.frontend_origin, f"guid_fetch_{type(exc).__name__}")

    if users_response.status_code != status.HTTP_200_OK:
        return _auth_error_redirect(
            settings.frontend_origin, f"guid_fetch_status_{users_response.status_code}; body={users_response.text[:200]!r}"
        )

    try:
        users_payload = users_response.json()
        yahoo_guid: str = _extract_yahoo_guid(users_payload)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        try:
            present = (
                sorted(users_payload.keys())
                if isinstance(users_payload, dict)
                else type(users_payload).__name__
            )
        except Exception:
            present = "unparseable"
        return _auth_error_redirect(
            settings.frontend_origin,
            f"guid_fetch_parse_miss ({type(exc).__name__}); keys={present}",
        )

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


# --- POST /api/auth/dev-login ---
#
# Seeds (idempotently) a fixed dev dataset and logs into it -- exists purely so
# Playwright/local smoke testing can reach the dashboard without a real Yahoo
# OAuth round trip. Gated 404 behind Settings.dev_auth_enabled, which defaults
# False and is never set true in a real deployment's env, so this route is
# unreachable (not just inert) in prod.

DEV_USER_GUID = "DEVUSER"
DEV_LEAGUE_KEY = "nba.l.999999"
DEV_TEAM_KEY = "nba.l.999999.t.1"
DEV_OTHER_TEAM_KEY = "nba.l.999999.t.2"
DEV_LEAGUE_SEASON = 2025

# real values from tests/fixtures/yahoo/league_settings.json (a live-shaped Yahoo
# settings response) -- keeps the dev league's roster_positions/categories/stat_ids
# identical to what a real synced league would carry, so draft valuation math
# (which reads stat_id + is_negative straight from settings_json) never has to
# special-case the dev fixture
_DEV_LEAGUE_SETTINGS = LeagueSettings(
    categories=[
        CategoryInfo(stat_id=5, name="Field Goal Percentage", display_name="FG%", is_negative=False),
        CategoryInfo(stat_id=8, name="Free Throw Percentage", display_name="FT%", is_negative=False),
        CategoryInfo(stat_id=10, name="3-point Shots Made", display_name="3PTM", is_negative=False),
        CategoryInfo(stat_id=12, name="Points Scored", display_name="PTS", is_negative=False),
        CategoryInfo(stat_id=15, name="Total Rebounds", display_name="REB", is_negative=False),
        CategoryInfo(stat_id=16, name="Assists", display_name="AST", is_negative=False),
        CategoryInfo(stat_id=17, name="Steals", display_name="ST", is_negative=False),
        CategoryInfo(stat_id=18, name="Blocked Shots", display_name="BLK", is_negative=False),
        # sort_order "0" (lower-is-better) -> is_negative=True, same as parse_league_settings
        CategoryInfo(stat_id=19, name="Turnovers", display_name="TO", is_negative=True),
    ],
    roster_positions=[
        RosterPosition(position="PG", count=1),
        RosterPosition(position="SG", count=1),
        RosterPosition(position="G", count=1),
        RosterPosition(position="SF", count=1),
        RosterPosition(position="PF", count=1),
        RosterPosition(position="F", count=1),
        RosterPosition(position="C", count=2),
        RosterPosition(position="UTIL", count=3),
        RosterPosition(position="BN", count=3),
        RosterPosition(position="IL", count=2),
    ],
    max_weekly_adds=4,
    playoff_start_week=20,
    num_playoff_teams=4,
)
DEV_LEAGUE_SETTINGS_JSON = asdict(_DEV_LEAGUE_SETTINGS)

# natural-key seed data for the three roster players; nba_person_id values live
# in a 900000+ block that no real nba_api sync will ever produce, so a dev run
# can never collide with real warehouse data
_DEV_PLAYERS = [
    {
        "person_id": 900001,
        "name": "Dev Player One",
        "position": "PG",
        "injury_status": None,
        "averages": {
            "fgm": 6.0, "fga": 13.0, "ftm": 4.0, "fta": 5.0, "tpm": 2.0,
            "pts": 18.0, "reb": 4.0, "ast": 7.0, "stl": 1.2, "blk": 0.3, "tov": 2.5,
        },
    },
    {
        "person_id": 900002,
        "name": "Dev Player Two",
        "position": "C",
        "injury_status": "INJ",
        "averages": {
            "fgm": 8.0, "fga": 14.0, "ftm": 5.0, "fta": 7.0, "tpm": 0.0,
            "pts": 21.0, "reb": 11.0, "ast": 2.0, "stl": 0.7, "blk": 1.8, "tov": 2.0,
        },
    },
    {
        "person_id": 900003,
        "name": "Dev Player Three",
        "position": "SG",
        "injury_status": None,
        "averages": {
            "fgm": 5.0, "fga": 11.0, "ftm": 2.0, "fta": 3.0, "tpm": 2.5,
            "pts": 14.5, "reb": 3.5, "ast": 3.0, "stl": 1.0, "blk": 0.2, "tov": 1.5,
        },
    },
]  # fmt: skip

# draftable pool: ~72 real, recognizable NBA players (names only -- these are
# hand-modeled realistic per-game lines for a demo, not licensed/official
# projections) spanning every position with plausible scarcity (few truly
# elite centers, deep guard/wing pool), and covering archetypes a knowledgeable
# fantasy player expects to see: two-way stars, punt-FT rim protectors, 3PM
# specialists, high-assist/low-scoring floor generals, and several
# injury-flagged players (low "games") for punt/risk scenarios. person_id
# block 900101-900199 extends the 900001-900003 dev-roster block without
# collision. Row shape: (person_id, name, position, games, fgm, fga, ftm,
# fta, tpm, reb, ast, stl, blk, tov) -- pts is derived below via
# pts = 2*fgm + tpm + ftm (equivalent to 2*(fgm-tpm) + 3*tpm + ftm), which
# keeps every row internally consistent by construction instead of by hand
# arithmetic.
#
# positions carry real dual Yahoo-style eligibility (e.g. "PF-C", "SG-SF")
# wherever a player is actually dual-eligible in real life -- most rotation
# bigs and wings are. A single-position tag (e.g. Jokic "C", Zion "PF") is
# reserved for players who are genuinely single-position in real Yahoo
# leagues. Without this, a pool that's 90%+ single-position understates
# replacement level at PF/SF (real bigs backstop those slots via their C/PF
# eligibility) and visibly distorts the draft board.
_DEV_POOL_RAW: list[tuple] = [
    (900101, "Nikola Jokic", "C", 78, 10.5, 16.0, 6.0, 7.0, 1.2, 11.5, 9.5, 1.2, 0.7, 3.0),
    (900102, "Luka Doncic", "PG-SG", 70, 10.0, 20.5, 7.5, 9.0, 3.5, 8.5, 8.5, 1.3, 0.5, 3.7),
    (900103, "Shai Gilgeous-Alexander", "PG-SG", 75, 10.5, 19.5, 7.0, 7.8, 1.5, 5.2, 6.2, 1.7, 1.0, 2.4),
    (900104, "Giannis Antetokounmpo", "SF-PF", 70, 11.5, 18.5, 6.5, 10.0, 0.5, 11.5, 6.0, 1.0, 1.1, 3.3),
    (900105, "Jayson Tatum", "SF-PF", 72, 9.5, 20.0, 5.5, 6.5, 3.0, 8.0, 4.5, 1.0, 0.6, 2.5),
    (900106, "Tyrese Haliburton", "PG", 70, 7.0, 14.5, 3.0, 3.5, 2.8, 3.8, 10.5, 1.3, 0.5, 2.4),
    (900107, "Anthony Edwards", "SG-SF", 75, 9.0, 19.5, 5.0, 6.0, 3.5, 5.5, 4.5, 1.3, 0.6, 3.0),
    (900108, "Domantas Sabonis", "PF-C", 78, 8.0, 13.0, 3.5, 4.5, 0.3, 13.0, 6.0, 0.9, 0.5, 2.9),
    (900109, "Devin Booker", "SG-PG", 68, 9.0, 19.0, 5.5, 6.3, 2.2, 4.5, 6.5, 0.9, 0.4, 2.8),
    (900110, "Donovan Mitchell", "SG-PG", 70, 8.8, 19.0, 5.0, 5.8, 3.2, 4.3, 4.9, 1.4, 0.4, 2.7),
    (900111, "Jalen Brunson", "PG-SG", 70, 9.0, 19.5, 5.5, 6.2, 2.5, 3.6, 7.3, 0.9, 0.2, 2.5),
    (900112, "Trae Young", "PG", 72, 7.5, 17.5, 6.0, 6.8, 3.0, 3.0, 10.8, 1.0, 0.1, 4.2),
    (900113, "De'Aaron Fox", "PG", 72, 8.5, 18.5, 4.5, 5.5, 1.8, 4.0, 5.8, 1.8, 0.4, 3.0),
    (900114, "Damian Lillard", "PG", 65, 7.8, 17.0, 5.5, 6.2, 4.0, 4.2, 6.5, 0.9, 0.3, 3.0),
    (900115, "Kawhi Leonard", "SF-PF", 50, 8.0, 15.5, 4.0, 4.5, 1.8, 6.2, 3.5, 1.5, 0.5, 1.8),
    (900116, "Joel Embiid", "C", 45, 8.5, 16.0, 8.5, 10.0, 1.2, 9.5, 4.0, 0.9, 1.5, 3.2),
    (900117, "Ja Morant", "PG", 55, 7.5, 16.5, 4.5, 5.8, 1.2, 4.0, 7.0, 1.0, 0.3, 3.0),
    (900118, "Zion Williamson", "PF", 48, 8.5, 14.0, 5.0, 7.5, 0.1, 6.8, 4.8, 1.0, 0.6, 3.0),
    (900119, "Jamal Murray", "PG-SG", 58, 7.5, 16.0, 3.5, 4.0, 2.3, 4.0, 6.0, 0.9, 0.3, 2.5),
    (900120, "Kristaps Porzingis", "PF-C", 50, 6.5, 13.0, 4.0, 4.8, 1.8, 7.2, 1.8, 0.7, 1.7, 1.8),
    (900121, "Paul George", "SG-SF", 58, 6.5, 14.5, 3.5, 4.2, 2.5, 5.5, 3.3, 1.4, 0.4, 2.3),
    (900122, "Bradley Beal", "SG", 55, 7.0, 14.5, 3.0, 3.5, 1.5, 4.2, 4.5, 0.9, 0.3, 2.2),
    (900123, "Rudy Gobert", "C", 75, 5.0, 7.5, 1.8, 3.5, 0.0, 11.5, 1.5, 0.7, 2.0, 1.8),
    (900124, "Ivica Zubac", "C", 78, 6.5, 10.5, 2.5, 4.5, 0.0, 11.5, 2.0, 0.6, 1.1, 1.5),
    (900125, "Clint Capela", "C", 72, 4.5, 7.0, 1.5, 3.0, 0.0, 10.5, 1.2, 0.6, 1.3, 1.3),
    (900126, "Nic Claxton", "C", 65, 4.8, 7.5, 1.3, 2.5, 0.0, 8.5, 1.8, 0.9, 2.0, 1.4),
    (900127, "Mitchell Robinson", "C", 58, 3.5, 5.0, 1.0, 2.2, 0.0, 8.5, 0.8, 0.5, 1.7, 1.0),
    (900128, "Jarrett Allen", "C", 75, 6.0, 9.0, 2.5, 3.8, 0.0, 9.8, 2.8, 0.9, 1.1, 1.5),
    (900129, "Buddy Hield", "SG", 78, 5.0, 11.5, 1.5, 1.8, 3.5, 3.5, 2.5, 0.7, 0.2, 1.3),
    (900130, "Klay Thompson", "SG-SF", 75, 5.5, 12.5, 1.2, 1.4, 3.2, 3.2, 2.2, 0.6, 0.4, 1.0),
    (900131, "Duncan Robinson", "SG", 72, 3.8, 8.5, 0.8, 0.9, 2.8, 2.5, 2.0, 0.5, 0.1, 1.0),
    (900132, "Sam Merrill", "SG", 75, 3.5, 7.8, 0.9, 1.0, 2.5, 2.3, 1.8, 0.7, 0.1, 0.8),
    (900133, "Max Strus", "SG-SF", 74, 4.0, 9.5, 1.2, 1.4, 2.7, 4.0, 2.5, 0.7, 0.2, 1.2),
    (900134, "Malik Beasley", "SG-SF", 78, 4.5, 10.5, 1.0, 1.2, 3.0, 3.2, 1.8, 0.8, 0.2, 1.0),
    (900135, "Tyus Jones", "PG", 75, 3.5, 7.5, 1.2, 1.4, 1.0, 2.5, 8.0, 1.1, 0.1, 1.3),
    (900136, "T.J. McConnell", "PG", 72, 4.0, 7.5, 1.5, 1.8, 0.2, 3.0, 6.5, 1.6, 0.2, 1.5),
    (900137, "Payton Pritchard", "PG-SG", 80, 5.5, 12.0, 1.8, 2.0, 3.2, 3.8, 4.5, 0.9, 0.2, 1.8),
    (900138, "Jose Alvarado", "PG", 65, 3.2, 7.0, 0.8, 1.0, 1.2, 2.2, 4.5, 1.5, 0.2, 1.5),
    (900139, "Jrue Holiday", "PG-SG", 75, 5.5, 11.5, 1.8, 2.2, 1.8, 4.8, 4.5, 1.2, 0.5, 1.7),
    (900140, "Derrick White", "PG-SG", 78, 5.8, 12.5, 1.5, 1.8, 2.5, 4.0, 4.8, 1.1, 1.0, 1.6),
    (900141, "Marcus Smart", "PG-SG", 65, 4.5, 10.5, 1.8, 2.2, 1.8, 3.5, 4.5, 1.5, 0.4, 2.0),
    (900142, "Alperen Sengun", "PF-C", 78, 7.5, 14.0, 4.0, 5.5, 0.3, 9.8, 5.2, 1.2, 0.9, 3.0),
    (900143, "Anthony Davis", "PF-C", 65, 9.5, 17.5, 5.0, 6.5, 0.5, 11.5, 3.2, 1.1, 2.0, 2.0),
    (900144, "Bam Adebayo", "PF-C", 78, 7.5, 14.0, 4.5, 5.8, 0.5, 9.5, 4.0, 1.1, 0.8, 2.5),
    (900145, "Karl-Anthony Towns", "PF-C", 72, 8.0, 15.5, 5.5, 6.2, 2.2, 12.5, 3.0, 0.7, 0.6, 2.8),
    (900146, "Evan Mobley", "PF-C", 75, 7.0, 12.0, 2.8, 4.0, 0.5, 9.5, 3.2, 0.8, 1.6, 2.0),
    (900147, "Victor Wembanyama", "PF-C", 65, 8.5, 16.5, 4.5, 5.8, 2.0, 11.0, 3.8, 1.2, 3.5, 2.8),
    (900148, "Chet Holmgren", "PF-C", 68, 6.5, 12.0, 2.5, 3.0, 1.8, 7.8, 2.5, 0.8, 2.2, 1.8),
    (900149, "Paolo Banchero", "SF-PF", 72, 8.5, 17.5, 5.5, 7.0, 1.5, 6.8, 4.0, 1.0, 0.5, 2.8),
    (900150, "Franz Wagner", "SF-PF", 78, 7.5, 14.5, 4.5, 5.5, 1.2, 5.2, 4.2, 1.0, 0.4, 2.0),
    (900151, "Jalen Williams", "SG-SF", 75, 7.0, 13.5, 3.5, 4.0, 1.3, 4.5, 4.8, 1.3, 0.6, 2.3),
    (900152, "Scottie Barnes", "SF-PF", 75, 7.2, 14.0, 3.0, 4.2, 1.2, 8.0, 5.8, 1.1, 0.8, 2.5),
    (900153, "Cade Cunningham", "PG", 70, 8.0, 17.5, 5.0, 6.0, 2.0, 4.5, 8.5, 1.0, 0.6, 4.2),
    (900154, "LaMelo Ball", "PG-SG", 60, 7.5, 17.0, 4.0, 4.8, 3.2, 5.5, 7.5, 1.4, 0.4, 3.5),
    (900155, "Coby White", "PG-SG", 78, 7.0, 15.5, 2.0, 2.5, 2.8, 4.2, 4.5, 0.8, 0.3, 2.5),
    (900156, "Jaylen Brown", "SG-SF", 70, 8.5, 18.0, 4.0, 5.0, 2.0, 5.5, 3.5, 1.1, 0.5, 2.8),
    (900157, "Mikal Bridges", "SG-SF", 80, 7.0, 14.5, 2.5, 3.0, 2.2, 4.5, 3.5, 1.0, 0.4, 1.8),
    (900158, "OG Anunoby", "SF-PF", 72, 5.5, 11.5, 1.8, 2.2, 2.3, 4.8, 2.2, 1.4, 0.6, 1.5),
    (900159, "Herbert Jones", "SF-PF", 72, 4.0, 8.5, 1.2, 1.5, 1.3, 4.0, 2.2, 1.5, 0.7, 1.2),
    (900160, "Deni Avdija", "SF-PF", 76, 6.5, 13.5, 3.0, 3.8, 1.8, 7.5, 4.5, 1.1, 0.5, 2.2),
    (900161, "Tyrese Maxey", "PG-SG", 78, 8.5, 18.5, 4.5, 5.2, 2.8, 3.8, 6.5, 1.2, 0.5, 2.5),
    (900162, "Darius Garland", "PG", 65, 7.0, 15.5, 3.0, 3.5, 2.5, 2.8, 6.8, 1.0, 0.1, 2.7),
    (900163, "Jalen Green", "SG", 72, 7.5, 17.0, 3.5, 4.2, 2.8, 4.0, 3.5, 0.8, 0.4, 2.6),
    (900164, "Anfernee Simons", "SG-PG", 72, 6.5, 14.5, 2.5, 2.8, 3.0, 3.0, 3.8, 0.7, 0.2, 2.0),
    (900165, "Norman Powell", "SG-SF", 76, 7.0, 14.5, 2.8, 3.2, 2.5, 3.2, 2.5, 0.9, 0.3, 1.5),
    (900166, "Walker Kessler", "C", 72, 4.0, 6.0, 1.2, 2.2, 0.0, 9.5, 1.2, 0.6, 2.3, 1.0),
    (900167, "Daniel Gafford", "C", 75, 4.5, 6.5, 1.5, 2.2, 0.0, 7.0, 1.0, 0.5, 1.4, 1.2),
    (900168, "Isaiah Hartenstein", "PF-C", 72, 4.5, 7.5, 1.5, 2.2, 0.1, 8.8, 3.5, 0.9, 1.0, 1.5),
    (900169, "Jalen Duren", "C", 74, 5.5, 8.5, 2.5, 4.5, 0.0, 10.5, 2.5, 0.7, 0.8, 2.0),
    (900170, "Michael Porter Jr.", "SF-PF", 74, 6.5, 13.5, 1.8, 2.2, 2.5, 6.8, 1.5, 0.7, 0.4, 1.5),
    (900171, "Brandon Ingram", "SF-PF", 65, 8.0, 17.0, 4.0, 4.8, 1.5, 5.2, 5.0, 0.8, 0.5, 2.8),
    (900172, "RJ Barrett", "SG-SF", 76, 6.8, 15.0, 3.2, 4.0, 1.5, 5.5, 4.2, 0.8, 0.3, 2.3),
]  # fmt: skip


def _pool_player(row: tuple) -> dict:
    person_id, name, position, games, fgm, fga, ftm, fta, tpm, reb, ast, stl, blk, tov = row
    # pts derived, not hand-entered: 2*(fgm-tpm) + 3*tpm + ftm simplifies to
    # 2*fgm + tpm + ftm -- deriving it here (rather than a 15th hand-typed
    # column) means every row is exactly internally consistent, not just
    # "close enough" by eyeball
    pts = round(2 * fgm + tpm + ftm, 1)
    return {
        "person_id": person_id,
        "name": name,
        "position": position,
        "games": games,
        "averages": {
            "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta, "tpm": tpm,
            "pts": pts, "reb": reb, "ast": ast, "stl": stl, "blk": blk, "tov": tov,
        },
    }  # fmt: skip


_DEV_POOL_PLAYERS = [_pool_player(row) for row in _DEV_POOL_RAW]


def _get_or_create_user(db: Session) -> User:
    user = db.execute(select(User).where(User.yahoo_guid == DEV_USER_GUID)).scalar_one_or_none()
    if user is None:
        user = User(yahoo_guid=DEV_USER_GUID, display_name="Dev User")
        db.add(user)
        db.flush()
    return user


def _get_or_create_league(db: Session) -> League:
    league = db.execute(
        select(League).where(League.yahoo_league_key == DEV_LEAGUE_KEY)
    ).scalar_one_or_none()
    if league is None:
        league = League(
            yahoo_league_key=DEV_LEAGUE_KEY,
            name="Dev League",
            season=DEV_LEAGUE_SEASON,
            num_teams=2,
            scoring_type="head",
            settings_json=DEV_LEAGUE_SETTINGS_JSON,
        )
        db.add(league)
        db.flush()
    elif league.settings_json != DEV_LEAGUE_SETTINGS_JSON:
        # self-heal: a league seeded before this constant existed (or before it
        # changed) would otherwise carry stale/empty settings_json forever, since
        # get-or-create only writes on insert -- re-login is the natural point to
        # bring it current, and it's a no-op once it matches
        league.settings_json = DEV_LEAGUE_SETTINGS_JSON
        db.flush()
    return league


def _get_or_create_team(
    db: Session,
    league: League,
    *,
    team_key: str,
    name: str,
    is_users_team: bool,
    user_id: int | None,
) -> Team:
    team = db.execute(select(Team).where(Team.yahoo_team_key == team_key)).scalar_one_or_none()
    if team is None:
        team = Team(
            league_id=league.id,
            yahoo_team_key=team_key,
            name=name,
            is_users_team=is_users_team,
            user_id=user_id,
        )
        db.add(team)
        db.flush()
    return team


def _get_or_create_standing(
    db: Session, league: League, team: Team, *, rank: int, wins: int, losses: int, ties: int
) -> None:
    existing = db.execute(
        select(Standing).where(Standing.league_id == league.id, Standing.team_id == team.id)
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            Standing(
                league_id=league.id, team_id=team.id, rank=rank, wins=wins, losses=losses, ties=ties
            )
        )
        db.flush()


def _get_or_create_roster_slot(
    db: Session, team: Team, *, player_key: str, name: str, position: str, injury_status: str | None
) -> None:
    existing = db.execute(
        select(RosterSlot).where(
            RosterSlot.team_id == team.id, RosterSlot.yahoo_player_key == player_key
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            RosterSlot(
                team_id=team.id,
                yahoo_player_key=player_key,
                player_name=name,
                position=position,
                injury_status=injury_status,
            )
        )
        db.flush()


def _get_or_create_nba_player(
    db: Session, *, person_id: int, full_name: str, position: str | None = None
) -> NbaPlayer:
    player = db.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == person_id)
    ).scalar_one_or_none()
    if player is None:
        player = NbaPlayer(nba_person_id=person_id, full_name=full_name, position=position)
        db.add(player)
        db.flush()
    elif player.full_name != full_name or player.position != position:
        # self-heal: get-or-create only writes on insert, so a row seeded
        # before the position column existed (or before a seed constant's
        # name/position changed) would otherwise carry stale data forever --
        # re-login is the natural point to bring it current; no-op once it
        # already matches (same pattern as League.settings_json above)
        player.full_name = full_name
        player.position = position
        db.flush()
    return player


def _get_or_create_player_id_map(
    db: Session, *, yahoo_player_key: str, yahoo_name: str, nba_player_id: int
) -> None:
    existing = db.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == yahoo_player_key)
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            PlayerIdMap(
                nba_player_id=nba_player_id,
                yahoo_player_key=yahoo_player_key,
                yahoo_name=yahoo_name,
                match_method="exact",
            )
        )
        db.flush()


def _get_or_create_season_average(
    db: Session,
    *,
    nba_player_id: int,
    season: str,
    averages: dict[str, float],
    games_played: int = 70,
) -> None:
    existing = db.execute(
        select(PlayerSeasonAverage).where(
            PlayerSeasonAverage.nba_player_id == nba_player_id,
            PlayerSeasonAverage.season == season,
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            PlayerSeasonAverage(
                nba_player_id=nba_player_id, season=season, games_played=games_played, **averages
            )
        )
        db.flush()
    else:
        # self-heal: an edited seed stat line must not be a silent no-op
        # against a pre-existing dev row (same rationale as NbaPlayer above)
        changed = existing.games_played != games_played
        existing.games_played = games_played
        for key, value in averages.items():
            if getattr(existing, key) != value:
                setattr(existing, key, value)
                changed = True
        if changed:
            db.flush()


def _get_or_create_projection(
    db: Session,
    *,
    nba_player_id: int,
    season: str,
    source: str,
    projected_games: int,
    averages: dict[str, float],
) -> None:
    # mirrors _get_or_create_season_average, keyed on the projection table's
    # actual unique constraint (nba_player_id, season, source) instead of just
    # (nba_player_id, season), since a player can carry projections from
    # multiple sources at once
    existing = db.execute(
        select(PlayerProjection).where(
            PlayerProjection.nba_player_id == nba_player_id,
            PlayerProjection.season == season,
            PlayerProjection.source == source,
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            PlayerProjection(
                nba_player_id=nba_player_id,
                season=season,
                source=source,
                projected_games=projected_games,
                **averages,
            )
        )
        db.flush()
    else:
        # self-heal: same rationale as _get_or_create_season_average above
        changed = existing.projected_games != projected_games
        existing.projected_games = projected_games
        for key, value in averages.items():
            if getattr(existing, key) != value:
                setattr(existing, key, value)
                changed = True
        if changed:
            db.flush()


def _warm_scoreboard_cache(db: Session, *, user_id: int, league_key: str) -> None:
    """Pre-populate the Yahoo scoreboard cache for the dev league.

    GET /api/leagues/{id}/overview calls the real YahooClient for the live
    matchup, which would try to refresh a Yahoo access token the dev user
    doesn't have and 401 the whole dashboard. A fresh cache row, keyed with
    the gateway's own _path_hash (not a reimplementation of it), makes the
    gateway serve this canned "no matchups" payload instead of ever touching
    the token refresh / network path. Always re-upserted (not get-or-create)
    so the cache is fresh -- and thus actually hit -- on every dev-login call.
    """
    resource_path = f"league/{league_key}/scoreboard"
    path_hash = _path_hash(resource_path)
    payload = {
        "fantasy_content": {
            "league": [
                {"league_key": league_key, "name": "Dev League"},
                {"scoreboard": [{"matchups": {"count": 0}}]},
            ]
        }
    }
    stmt = pg_insert(YahooApiCache).values(
        user_id=user_id, path_hash=path_hash, payload=payload, fetched_at=datetime.now(timezone.utc)
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "path_hash"],
        set_={"payload": stmt.excluded.payload, "fetched_at": stmt.excluded.fetched_at},
    )
    db.execute(stmt)
    db.flush()


@router.post("/api/auth/dev-login", status_code=status.HTTP_204_NO_CONTENT)
def dev_login(db: Session = Depends(get_session)) -> Response:
    settings = get_settings()
    # this flag can never be true in prod (see module comment above) -- this
    # assertion is the entire access control for an otherwise unauthenticated,
    # data-seeding endpoint
    if not settings.dev_auth_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    user = _get_or_create_user(db)
    league = _get_or_create_league(db)
    dev_team = _get_or_create_team(
        db, league, team_key=DEV_TEAM_KEY, name="Dev Team", is_users_team=True, user_id=user.id
    )
    other_team = _get_or_create_team(
        db, league, team_key=DEV_OTHER_TEAM_KEY, name="Rival Team", is_users_team=False, user_id=None
    )
    _get_or_create_standing(db, league, dev_team, rank=1, wins=10, losses=5, ties=0)
    _get_or_create_standing(db, league, other_team, rank=2, wins=7, losses=8, ties=0)

    for spec in _DEV_PLAYERS:
        player_key = f"{DEV_LEAGUE_KEY}.p.{spec['person_id']}"
        _get_or_create_roster_slot(
            db,
            dev_team,
            player_key=player_key,
            name=spec["name"],
            position=spec["position"],
            injury_status=spec["injury_status"],
        )
        nba_player = _get_or_create_nba_player(
            db, person_id=spec["person_id"], full_name=spec["name"], position=spec["position"]
        )
        _get_or_create_player_id_map(
            db, yahoo_player_key=player_key, yahoo_name=spec["name"], nba_player_id=nba_player.id
        )
        _get_or_create_season_average(
            db, nba_player_id=nba_player.id, season=settings.current_season, averages=spec["averages"]
        )

    # draftable pool: unrostered players (no RosterSlot) so the draft board has
    # something to rank without ever calling Yahoo. Each gets a season average
    # AND a projection row -- the engine prefers the projection, falling back
    # to the average, so both paths are exercised by the same dev data.
    for spec in _DEV_POOL_PLAYERS:
        player_key = f"{DEV_LEAGUE_KEY}.p.{spec['person_id']}"
        nba_player = _get_or_create_nba_player(
            db, person_id=spec["person_id"], full_name=spec["name"], position=spec["position"]
        )
        _get_or_create_player_id_map(
            db, yahoo_player_key=player_key, yahoo_name=spec["name"], nba_player_id=nba_player.id
        )
        _get_or_create_season_average(
            db,
            nba_player_id=nba_player.id,
            season=settings.current_season,
            averages=spec["averages"],
            games_played=spec["games"],
        )
        _get_or_create_projection(
            db,
            nba_player_id=nba_player.id,
            season=settings.current_season,
            source="dev-seed",
            projected_games=spec["games"],
            averages=spec["averages"],
        )

    _warm_scoreboard_cache(db, user_id=user.id, league_key=DEV_LEAGUE_KEY)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_on_response(response, user.id)
    return response
