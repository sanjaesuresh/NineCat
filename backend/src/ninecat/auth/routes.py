"""Yahoo OAuth2 login/callback/logout routes.

Login and logout live under /api; the callback intentionally does not, because its
path must exactly match https://localhost:8000/auth/yahoo/callback as registered
with Yahoo -- /api/auth/yahoo/callback would not match the registered redirect URI.
"""

import logging
import secrets
from collections.abc import Generator
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.auth.crypto import encrypt_token
from ninecat.auth.sessions import SESSION_COOKIE_NAME, set_session_on_response
from ninecat.config import get_settings
from ninecat.db import get_session
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
# reuse the warehouse's own upsert (idempotent + self-healing NbaTeam/NbaGame
# rows on rerun) instead of hand-rolling a second copy of that logic here --
# one code path owns "how a schedule row becomes NbaTeam/NbaGame rows"
from ninecat.warehouse.nba_schedule import sync_schedule

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
# league.season used to be a hardcoded literal here, independent of the
# current_season setting -- it would silently go stale the moment that setting
# was bumped for a new NBA season. Derived instead, at call time (not at
# import time, so a test's monkeypatch+cache_clear of current_season takes
# effect): config.py documents this exact leading-4-digits conversion as the
# sanctioned way to get League.season's plain start-year int from the
# hyphenated "YYYY-YY" setting.


def _dev_league_season() -> int:
    return int(get_settings().current_season[:4])


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


# --- NBA teams, schedule, and player-to-team links (Matchup Monitor demo data) ---
#
# Without these, warehouse/nba_schedule.py's games_in_range returns 0 for every
# seeded player (no NbaTeam/NbaGame rows, NbaPlayer.nba_team_id always NULL), which
# renders every weekly projection as zeros -- see docs/matchup-monitor-plan.md M2.

# monday-to-sunday demo week. Fixed, never date.today(), so the seed (and any test
# pinning it) is deterministic. Chosen to land on a real fantasy-week boundary under
# Settings.fantasy_season_start (2025-10-20, week 1) + 6*7 days = week 7, so a later
# week-derivation feature that anchors off that same constant agrees with this seed.
DEMO_WEEK_START = date(2025, 12, 1)
DEMO_WEEK_END = date(2025, 12, 7)
DEMO_WEEK_NUMBER = 7

# real NBA.com team ids (the stable, public constants nba_api and every stats.nba.com
# consumer use) keyed by abbreviation -- games_in_range resolves by this NBA.com id,
# not the internal NbaTeam PK, so these must be the real ones, not made up.
_DEV_NBA_TEAM_INFO: dict[str, tuple[int, str]] = {
    "ATL": (1610612737, "Atlanta Hawks"),
    "BOS": (1610612738, "Boston Celtics"),
    "BKN": (1610612751, "Brooklyn Nets"),
    "CHA": (1610612766, "Charlotte Hornets"),
    "CHI": (1610612741, "Chicago Bulls"),
    "CLE": (1610612739, "Cleveland Cavaliers"),
    "DAL": (1610612742, "Dallas Mavericks"),
    "DEN": (1610612743, "Denver Nuggets"),
    "DET": (1610612765, "Detroit Pistons"),
    "GSW": (1610612744, "Golden State Warriors"),
    "HOU": (1610612745, "Houston Rockets"),
    "IND": (1610612754, "Indiana Pacers"),
    "LAC": (1610612746, "LA Clippers"),
    "LAL": (1610612747, "Los Angeles Lakers"),
    "MEM": (1610612763, "Memphis Grizzlies"),
    "MIA": (1610612748, "Miami Heat"),
    "MIL": (1610612749, "Milwaukee Bucks"),
    "MIN": (1610612750, "Minnesota Timberwolves"),
    "NOP": (1610612740, "New Orleans Pelicans"),
    "NYK": (1610612752, "New York Knicks"),
    "OKC": (1610612760, "Oklahoma City Thunder"),
    "ORL": (1610612753, "Orlando Magic"),
    "PHI": (1610612755, "Philadelphia 76ers"),
    "PHX": (1610612756, "Phoenix Suns"),
    "POR": (1610612757, "Portland Trail Blazers"),
    "SAC": (1610612758, "Sacramento Kings"),
    "SAS": (1610612759, "San Antonio Spurs"),
    "TOR": (1610612761, "Toronto Raptors"),
    "UTA": (1610612762, "Utah Jazz"),
    "WAS": (1610612764, "Washington Wizards"),
}

# each real pool player's actual current NBA team (post-2025-offseason rosters, to
# the best of available knowledge -- a handful of role-player free-agency landing
# spots are less certain than the stars' and are called out below). The 3 fictional
# roster players (900001-900003) all land on Washington, the one team with no pool
# player, so every one of the 30 real NBA teams is represented in the demo schedule.
_DEV_PLAYER_TEAM_ABBR: dict[int, str] = {
    900001: "WAS", 900002: "WAS", 900003: "WAS",
    900101: "DEN",  # Jokic
    900102: "LAL",  # Doncic (Feb 2025 trade to LAL)
    900103: "OKC",  # Gilgeous-Alexander
    900104: "MIL",  # Antetokounmpo
    900105: "BOS",  # Tatum
    900106: "IND",  # Haliburton
    900107: "MIN",  # Edwards
    900108: "SAC",  # Sabonis
    900109: "PHX",  # Booker
    900110: "CLE",  # Mitchell
    900111: "NYK",  # Brunson
    900112: "ATL",  # Young
    900113: "SAS",  # Fox (Feb 2025 trade to SAS)
    900114: "POR",  # Lillard (Bucks stretch-waived him 2025 offseason; re-signed POR)
    900115: "LAC",  # Leonard
    900116: "PHI",  # Embiid
    900117: "MEM",  # Morant
    900118: "NOP",  # Williamson
    900119: "DEN",  # Murray
    900120: "ATL",  # Porzingis (traded BOS->ATL, 2025 offseason)
    900121: "PHI",  # George
    900122: "LAC",  # Beal (bought out by PHX, signed LAC, 2025 offseason)
    900123: "MIN",  # Gobert
    900124: "LAC",  # Zubac
    900125: "HOU",  # Capela
    900126: "BKN",  # Claxton
    900127: "NYK",  # Robinson
    900128: "CLE",  # Allen
    900129: "GSW",  # Hield
    900130: "DAL",  # Thompson
    900131: "MIA",  # D. Robinson
    900132: "CLE",  # Merrill
    900133: "CLE",  # Strus
    900134: "DET",  # Beasley (less certain -- 2025 offseason free agency)
    900135: "DEN",  # Jones (less certain -- 2024-25 in-season trade destination)
    900136: "IND",  # McConnell
    900137: "BOS",  # Pritchard
    900138: "NOP",  # Alvarado
    900139: "POR",  # Holiday (Feb 2025 trade BOS->POR for Simons)
    900140: "BOS",  # White
    900141: "LAL",  # Smart (less certain -- 2024-25 in-season trade chain)
    900142: "HOU",  # Sengun
    900143: "DAL",  # Davis (Feb 2025 trade for Doncic)
    900144: "MIA",  # Adebayo
    900145: "NYK",  # Towns (2024 offseason trade to NYK)
    900146: "CLE",  # Mobley
    900147: "SAS",  # Wembanyama
    900148: "OKC",  # Holmgren
    900149: "ORL",  # Banchero
    900150: "ORL",  # Wagner
    900151: "OKC",  # Williams
    900152: "TOR",  # Barnes
    900153: "DET",  # Cunningham
    900154: "CHA",  # Ball
    900155: "CHI",  # White
    900156: "BOS",  # Brown
    900157: "NYK",  # Bridges (2024 offseason trade to NYK)
    900158: "NYK",  # Anunoby
    900159: "NOP",  # Jones
    900160: "POR",  # Avdija
    900161: "PHI",  # Maxey
    900162: "CLE",  # Garland
    900163: "PHX",  # Green (2025 offseason Durant trade, HOU->PHX)
    900164: "BOS",  # Simons (Feb 2025 trade POR->BOS for Holiday)
    900165: "MIA",  # Powell
    900166: "UTA",  # Kessler
    900167: "DAL",  # Gafford
    900168: "HOU",  # Hartenstein
    900169: "DET",  # Duren
    900170: "BKN",  # Porter Jr. (2025 offseason trade DEN->BKN)
    900171: "TOR",  # Ingram
    900172: "TOR",  # Barrett
}

# a demo week's worth of games (48 total, mirrors a real week's ~45-55 league-wide
# count): most of the 30 teams play 3-4 games, 5 play only 2, and several (BOS, HOU,
# CLE, NYK among them) have a genuine back-to-back -- without this spread the
# streaming/add-schedule optimizer has nothing to optimize (every team would look
# identical). (day offset from DEMO_WEEK_START, home abbr, away abbr).
_DEV_GAMES: list[tuple[int, str, str]] = [
    (0, "BKN", "SAS"), (0, "BOS", "MIA"), (0, "DEN", "CLE"), (0, "HOU", "IND"),
    (0, "LAC", "ORL"), (0, "MIL", "TOR"), (0, "SAC", "CHI"),
    (1, "BOS", "DEN"), (1, "CHA", "ATL"), (1, "DAL", "PHX"), (1, "MEM", "HOU"),
    (1, "MIN", "ORL"), (1, "PHI", "MIA"), (1, "POR", "OKC"),
    (2, "BKN", "POR"), (2, "GSW", "LAL"), (2, "IND", "NYK"), (2, "LAC", "PHX"),
    (2, "NOP", "CLE"), (2, "TOR", "OKC"),
    (3, "ATL", "DEN"), (3, "CHI", "MIL"), (3, "CLE", "BOS"), (3, "DAL", "PHI"),
    (3, "DET", "MEM"), (3, "GSW", "SAS"), (3, "LAC", "NYK"), (3, "SAC", "MIN"),
    (4, "DEN", "SAS"), (4, "DET", "MIA"), (4, "HOU", "WAS"), (4, "NOP", "UTA"),
    (4, "PHI", "MIN"), (4, "POR", "TOR"),
    (5, "ATL", "LAL"), (5, "CHA", "ORL"), (5, "DAL", "HOU"), (5, "LAC", "NYK"),
    (5, "MEM", "BOS"), (5, "MIA", "MIL"),
    (6, "DET", "OKC"), (6, "MIN", "PHX"), (6, "NOP", "IND"), (6, "NYK", "UTA"),
    (6, "ORL", "CLE"), (6, "PHI", "GSW"), (6, "SAC", "BKN"), (6, "WAS", "DAL"),
]  # fmt: skip


def _dev_schedule_fetcher(season: str) -> list[dict]:
    """sync_schedule Fetcher for _DEV_GAMES -- shapes the fixed demo week as the
    same ScheduleRow dicts a live nba_api response would produce, so sync_schedule's
    own (idempotent, self-healing) upsert is the only place that logic lives."""
    rows = []
    for day_offset, home_abbr, away_abbr in _DEV_GAMES:
        game_date = DEMO_WEEK_START + timedelta(days=day_offset)
        home_id, home_name = _DEV_NBA_TEAM_INFO[home_abbr]
        away_id, away_name = _DEV_NBA_TEAM_INFO[away_abbr]
        rows.append(
            {
                # deterministic, collision-free with real nba_game_ids (nba.com's
                # are all-numeric) and stable across reruns for idempotency
                "game_id": f"dev-{game_date.isoformat()}-{home_abbr}-{away_abbr}",
                "game_date": game_date.isoformat(),
                "home_team_id": home_id,
                "home_team_name": home_name,
                "home_team_abbreviation": home_abbr,
                "away_team_id": away_id,
                "away_team_name": away_name,
                "away_team_abbreviation": away_abbr,
            }
        )
    return rows


# pool players who fill out the two demo rosters beyond the 3 fixed dev-team
# players (see task item 6) and the rival team (which otherwise has a standings
# row but no roster at all). Deliberately different category shapes: the dev
# team leans guard/playmaking (AST, 3PM, ST), the rival leans bigs/rim protection
# (REB, BLK, FG%) -- a real "punt AST" build -- so the matchup comparison has
# actual contrast instead of two similar-looking teams. Disjoint by construction
# (checked in tests) so both are valid, non-overlapping league rosters.
_DEV_USER_EXTRA_ROSTER_IDS: list[int] = [
    900111,  # Brunson
    900113,  # Fox
    900140,  # White
    900161,  # Maxey
    900162,  # Garland
    900136,  # McConnell
    900137,  # Pritchard
    900157,  # Bridges
    900108,  # Sabonis
    900126,  # Claxton
]
_DEV_RIVAL_ROSTER_IDS: list[int] = [
    900123,  # Gobert
    900124,  # Zubac
    900125,  # Capela
    900166,  # Kessler
    900168,  # Hartenstein
    900142,  # Sengun
    900143,  # Davis
    900144,  # Adebayo
    900146,  # Mobley
    900127,  # Robinson
    900128,  # Allen
    900167,  # Gafford
    900169,  # Duren
]
_DEV_ROSTER_ASSIGNMENTS: dict[int, str] = {
    **{pid: "user" for pid in _DEV_USER_EXTRA_ROSTER_IDS},
    **{pid: "rival" for pid in _DEV_RIVAL_ROSTER_IDS},
}


# every helper below used to be a plain SELECT-then-INSERT-if-missing: two
# concurrent dev-logins (two real Yahoo test users hitting /api/auth/dev-login
# at once, or a test suite racing against a live e2e run) can both pass the
# SELECT before either INSERT lands, and the loser's INSERT then dies on the
# row's unique constraint (live-observed: frontend/e2e/draft.spec.ts had to
# serialize itself around exactly this, and a backend-suite run overlapping a
# second process produced a real IntegrityError in test_dev_login_is_idempotent).
# Every one of these now does a single atomic ON CONFLICT statement instead --
# the same pattern the warehouse sync modules already use (nba_schedule.py,
# player_stats.py, fantasy_weeks.py) -- so two racing sessions each get a
# consistent row back with no unhandled-constraint window between them. Rows
# that need to self-heal drifted seed data use DO UPDATE (unconditional
# overwrite, matching nba_schedule.sync_schedule's convention); rows that are
# genuinely create-once use DO NOTHING. Every helper re-selects afterward
# rather than trusting RETURNING, since DO NOTHING returns no row when another
# session already won the race (same rationale as fantasy_weeks.resolve_week).


def _get_or_create_user(db: Session) -> User:
    stmt = pg_insert(User).values(yahoo_guid=DEV_USER_GUID, display_name="Dev User")
    stmt = stmt.on_conflict_do_nothing(index_elements=[User.yahoo_guid])
    db.execute(stmt)
    db.flush()
    return db.execute(select(User).where(User.yahoo_guid == DEV_USER_GUID)).scalar_one()


def _get_or_create_league(db: Session) -> League:
    insert_stmt = pg_insert(League).values(
        yahoo_league_key=DEV_LEAGUE_KEY,
        name="Dev League",
        season=_dev_league_season(),
        num_teams=2,
        scoring_type="head",
        settings_json=DEV_LEAGUE_SETTINGS_JSON,
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[League.yahoo_league_key],
        set_={
            # self-heal: a league seeded before this constant existed (or
            # before current_season was bumped) would otherwise carry
            # stale/empty settings_json or a stale season forever -- re-login
            # is the natural point to bring it current
            "season": insert_stmt.excluded.season,
            "settings_json": insert_stmt.excluded.settings_json,
        },
    )
    db.execute(stmt)
    db.flush()
    return db.execute(
        select(League).where(League.yahoo_league_key == DEV_LEAGUE_KEY)
    ).scalar_one()


def _get_or_create_team(
    db: Session,
    league: League,
    *,
    team_key: str,
    name: str,
    is_users_team: bool,
    user_id: int | None,
) -> Team:
    stmt = pg_insert(Team).values(
        league_id=league.id,
        yahoo_team_key=team_key,
        name=name,
        is_users_team=is_users_team,
        user_id=user_id,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=[Team.yahoo_team_key])
    db.execute(stmt)
    db.flush()
    return db.execute(select(Team).where(Team.yahoo_team_key == team_key)).scalar_one()


def _get_or_create_standing(
    db: Session, league: League, team: Team, *, rank: int, wins: int, losses: int, ties: int
) -> None:
    stmt = pg_insert(Standing).values(
        league_id=league.id, team_id=team.id, rank=rank, wins=wins, losses=losses, ties=ties
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=[Standing.league_id, Standing.team_id])
    db.execute(stmt)
    db.flush()


def _get_or_create_roster_slot(
    db: Session, team: Team, *, player_key: str, name: str, position: str, injury_status: str | None
) -> None:
    stmt = pg_insert(RosterSlot).values(
        team_id=team.id,
        yahoo_player_key=player_key,
        player_name=name,
        position=position,
        injury_status=injury_status,
    )
    stmt = stmt.on_conflict_do_nothing(
        index_elements=[RosterSlot.team_id, RosterSlot.yahoo_player_key]
    )
    db.execute(stmt)
    db.flush()


def _get_or_create_nba_player(
    db: Session,
    *,
    person_id: int,
    full_name: str,
    position: str | None = None,
    nba_team_id: int | None = None,
) -> NbaPlayer:
    insert_stmt = pg_insert(NbaPlayer).values(
        nba_person_id=person_id, full_name=full_name, position=position, nba_team_id=nba_team_id
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[NbaPlayer.nba_person_id],
        set_={
            # self-heal: a row seeded before the position column existed (or
            # before a seed constant's name/position/team changed) would
            # otherwise carry stale data forever -- re-login is the natural
            # point to bring it current; no-op once it already matches
            "full_name": insert_stmt.excluded.full_name,
            "position": insert_stmt.excluded.position,
            "nba_team_id": insert_stmt.excluded.nba_team_id,
        },
    )
    db.execute(stmt)
    db.flush()
    return db.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == person_id)
    ).scalar_one()


def _get_or_create_player_id_map(
    db: Session, *, yahoo_player_key: str, yahoo_name: str, nba_player_id: int
) -> None:
    stmt = pg_insert(PlayerIdMap).values(
        nba_player_id=nba_player_id,
        yahoo_player_key=yahoo_player_key,
        yahoo_name=yahoo_name,
        match_method="exact",
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=[PlayerIdMap.yahoo_player_key])
    db.execute(stmt)
    db.flush()


def _get_or_create_season_average(
    db: Session,
    *,
    nba_player_id: int,
    season: str,
    averages: dict[str, float],
    games_played: int = 70,
) -> None:
    insert_stmt = pg_insert(PlayerSeasonAverage).values(
        nba_player_id=nba_player_id, season=season, games_played=games_played, **averages
    )
    stmt = insert_stmt.on_conflict_do_update(
        # (nba_player_id, season) is the table's actual unique constraint
        index_elements=[PlayerSeasonAverage.nba_player_id, PlayerSeasonAverage.season],
        set_={
            # self-heal: an edited seed stat line must not be a silent no-op
            # against a pre-existing dev row (same rationale as NbaPlayer above)
            "games_played": insert_stmt.excluded.games_played,
            **{key: getattr(insert_stmt.excluded, key) for key in averages},
            # onupdate=func.now() on the column does NOT fire for ON CONFLICT
            # updates (SQLAlchemy only applies onupdate to ORM-driven UPDATEs),
            # so it must be set explicitly here, same fix as
            # warehouse/nba_schedule.py's sync_schedule
            "synced_at": func.now(),
        },
    )
    db.execute(stmt)
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
    insert_stmt = pg_insert(PlayerProjection).values(
        nba_player_id=nba_player_id,
        season=season,
        source=source,
        projected_games=projected_games,
        **averages,
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[
            PlayerProjection.nba_player_id,
            PlayerProjection.season,
            PlayerProjection.source,
        ],
        set_={
            # self-heal: same rationale as _get_or_create_season_average above
            "projected_games": insert_stmt.excluded.projected_games,
            **{key: getattr(insert_stmt.excluded, key) for key in averages},
            "synced_at": func.now(),
        },
    )
    db.execute(stmt)
    db.flush()


def _warm_scoreboard_cache(db: Session, *, user_id: int, league_key: str) -> None:
    """Pre-populate the Yahoo scoreboard cache for the dev league.

    GET /api/leagues/{id}/overview calls the real YahooClient for the live
    matchup, which would try to refresh a Yahoo access token the dev user
    doesn't have and 401 the whole dashboard. A fresh cache row, keyed with
    the gateway's own _path_hash (not a reimplementation of it), makes the
    gateway serve this canned matchup payload instead of ever touching the
    token refresh / network path. Always re-upserted (not get-or-create) so
    the cache is fresh -- and thus actually hit -- on every dev-login call.

    The payload shape mirrors tests/fixtures/yahoo/league_scoreboard.json (the
    shape parse_scoreboard actually walks) and carries a real dev-team-vs-rival
    matchup for DEMO_WEEK_NUMBER: stat_ids match DEV_LEAGUE_SETTINGS_JSON's
    categories, and the two lines are deliberately lopsided in different
    categories (dev team ahead on AST/3PM/ST, rival ahead on REB/BLK/FG%) to
    match the two rosters' guard-heavy vs big-heavy builds -- these are a
    plausible weekly scoreboard snapshot, not derived from the roster/schedule
    seeded below, since a live scoreboard and a weekly projection are two
    different kinds of number.
    """
    resource_path = f"league/{league_key}/scoreboard"
    path_hash = _path_hash(resource_path)

    def _team_block(team_key: str, name: str, stat_values: list[str]) -> dict:
        stat_ids = [c.stat_id for c in _DEV_LEAGUE_SETTINGS.categories]
        return {
            "team": [
                [{"team_key": team_key}, {"name": name}],
                {
                    "team_stats": {
                        "stats": [
                            {"stat": {"stat_id": str(stat_id), "value": value}}
                            for stat_id, value in zip(stat_ids, stat_values)
                        ]
                    }
                },
            ]
        }

    payload = {
        "fantasy_content": {
            "league": [
                {"league_key": league_key, "name": "Dev League"},
                {
                    "scoreboard": [
                        {
                            "matchups": {
                                "0": {
                                    "matchup": {
                                        "week": str(DEMO_WEEK_NUMBER),
                                        "0": {
                                            "teams": {
                                                "0": _team_block(
                                                    DEV_TEAM_KEY,
                                                    "Dev Team",
                                                    # FG% FT% 3PTM PTS REB AST ST BLK TO
                                                    [".478", ".812", "42", "612", "210", "178", "48", "22", "68"],
                                                ),
                                                "1": _team_block(
                                                    DEV_OTHER_TEAM_KEY,
                                                    "Rival Team",
                                                    [".512", ".734", "18", "598", "298", "112", "39", "51", "54"],
                                                ),
                                                "count": 2,
                                            }
                                        },
                                    }
                                },
                                "count": 1,
                            }
                        }
                    ]
                },
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

    # demo week of NbaGame rows (see _DEV_GAMES) -- without this, every seeded
    # player's games_in_range is 0 and all weekly projection math renders as
    # zeros. sync_schedule upserts NbaTeam rows too, so this must run before any
    # _get_or_create_nba_player call below that needs to resolve a team's
    # internal id.
    sync_schedule(db, season=settings.current_season, fetcher=_dev_schedule_fetcher)
    db.flush()
    # sync_schedule keys NbaTeam by NBA.com's own id; invert that back to
    # abbreviation so each player lookup below can go abbr -> internal PK
    # (the FK NbaPlayer.nba_team_id actually stores) in one step
    _nba_team_id_to_abbr = {
        nba_team_id: abbr for abbr, (nba_team_id, _name) in _DEV_NBA_TEAM_INFO.items()
    }
    teams = (
        db.execute(select(NbaTeam).where(NbaTeam.nba_team_id.in_(_nba_team_id_to_abbr)))
        .scalars()
        .all()
    )
    team_internal_id_by_abbr: dict[str, int] = {
        _nba_team_id_to_abbr[team.nba_team_id]: team.id for team in teams
    }

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
            db,
            person_id=spec["person_id"],
            full_name=spec["name"],
            position=spec["position"],
            nba_team_id=team_internal_id_by_abbr[_DEV_PLAYER_TEAM_ABBR[spec["person_id"]]],
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
    # to the average, so both paths are exercised by the same dev data. A
    # subset (_DEV_ROSTER_ASSIGNMENTS) also gets a RosterSlot on the dev team or
    # rival team, so the draft board's league-wide rostered-player exclusion
    # (api/routes.py's _league_rostered_player_ids) removes them from free
    # agents same as it would for a real synced league.
    for spec in _DEV_POOL_PLAYERS:
        player_key = f"{DEV_LEAGUE_KEY}.p.{spec['person_id']}"
        nba_player = _get_or_create_nba_player(
            db,
            person_id=spec["person_id"],
            full_name=spec["name"],
            position=spec["position"],
            nba_team_id=team_internal_id_by_abbr[_DEV_PLAYER_TEAM_ABBR[spec["person_id"]]],
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
        roster_team = _DEV_ROSTER_ASSIGNMENTS.get(spec["person_id"])
        if roster_team is not None:
            _get_or_create_roster_slot(
                db,
                dev_team if roster_team == "user" else other_team,
                player_key=player_key,
                name=spec["name"],
                position=spec["position"],
                injury_status=None,
            )

    _warm_scoreboard_cache(db, user_id=user.id, league_key=DEV_LEAGUE_KEY)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_on_response(response, user.id)
    return response
