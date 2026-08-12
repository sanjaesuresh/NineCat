"""Yahoo OAuth2 login/callback/logout routes.

Login and logout live under /api; the callback intentionally does not, because its
path must exactly match https://localhost:8000/auth/yahoo/callback as registered
with Yahoo -- /api/auth/yahoo/callback would not match the registered redirect URI.
"""

import logging
import secrets
from collections.abc import Generator
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
            settings.frontend_origin, f"guid_fetch_status_{users_response.status_code}"
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
            settings_json={},
        )
        db.add(league)
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


def _get_or_create_nba_player(db: Session, *, person_id: int, full_name: str) -> NbaPlayer:
    player = db.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == person_id)
    ).scalar_one_or_none()
    if player is None:
        player = NbaPlayer(nba_person_id=person_id, full_name=full_name)
        db.add(player)
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
    db: Session, *, nba_player_id: int, season: str, averages: dict[str, float]
) -> None:
    existing = db.execute(
        select(PlayerSeasonAverage).where(
            PlayerSeasonAverage.nba_player_id == nba_player_id,
            PlayerSeasonAverage.season == season,
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(PlayerSeasonAverage(nba_player_id=nba_player_id, season=season, games_played=70, **averages))
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
            db, person_id=spec["person_id"], full_name=spec["name"]
        )
        _get_or_create_player_id_map(
            db, yahoo_player_key=player_key, yahoo_name=spec["name"], nba_player_id=nba_player.id
        )
        _get_or_create_season_average(
            db, nba_player_id=nba_player.id, season=settings.current_season, averages=spec["averages"]
        )

    _warm_scoreboard_cache(db, user_id=user.id, league_key=DEV_LEAGUE_KEY)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_on_response(response, user.id)
    return response
