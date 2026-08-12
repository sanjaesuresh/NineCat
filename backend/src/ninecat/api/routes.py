"""Dashboard API: wires auth, sync, warehouse, and the engine into the JSON
API frontend/lib/api.ts consumes.

Every response shape here must match frontend/lib/api.ts's TypeScript
interfaces exactly (field-for-field) -- that file, not this module's own
judgment, is the source of truth for what the frontend expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ninecat.auth.sessions import SESSION_COOKIE_NAME, current_user
from ninecat.config import get_settings
from ninecat.db import get_session
from ninecat.engine import CATEGORIES, PlayerAverages, compute_player_zscores, compute_team_profile
from ninecat.models import (
    League,
    NbaPlayer,
    PlayerIdMap,
    PlayerSeasonAverage,
    RosterSlot,
    Standing,
    Team,
    User,
    YahooToken,
)
from ninecat.sync.league_sync import sync_league_detail, sync_user_leagues
from ninecat.warehouse.id_mapping import map_yahoo_players
from ninecat.yahoo.client import YahooClient
from ninecat.yahoo.gateway import YahooAuthError, YahooGateway, YahooUnavailableError
from ninecat.yahoo.parsers import UserTeamInfo

router = APIRouter()

_HEADSHOT_URL_TEMPLATE = "https://cdn.nba.com/headshots/nba/latest/1040x760/{nba_person_id}.png"


def get_yahoo_client(
    user: User = Depends(current_user), db: Session = Depends(get_session)
) -> YahooClient:
    """FastAPI dependency building a live YahooClient for the signed-in user.

    Overridden in tests (app.dependency_overrides) with a stub -- no route
    handler ever needs to know whether it's talking to a real gateway or not.
    """
    return YahooClient(YahooGateway(db, user.id))


@dataclass(frozen=True)
class _RosterPlayerAdapter:
    """Adapts a RosterSlot row to the .player_key/.name shape map_yahoo_players expects."""

    player_key: str
    name: str


def _league_dict(league: League) -> dict:
    return {
        "id": league.id,
        "yahoo_league_key": league.yahoo_league_key,
        "name": league.name,
        # League.season is stored as int; the frontend contract (League.season) is a string
        "season": str(league.season),
        "synced_at": league.synced_at.isoformat() if league.synced_at is not None else None,
    }


def _linked_leagues(db: Session, user: User) -> list[League]:
    """Every League this user has a claimed Team row in, ordered for stable output."""
    league_ids = db.execute(
        select(Team.league_id).where(Team.user_id == user.id).distinct()
    ).scalars().all()
    if not league_ids:
        return []
    return (
        db.execute(select(League).where(League.id.in_(league_ids)).order_by(League.id))
        .scalars()
        .all()
    )


def _get_owned_league(db: Session, user: User, league_id: int) -> League:
    """Resolve a path league_id, 404ing if it isn't linked to this user via Team.user_id.

    Leagues are cross-user shared rows (many managers' Team rows point at the same
    League), so ownership must be checked on every league-scoped route -- otherwise
    one user could read another manager's roster/standings just by guessing an id.
    """
    league = (
        db.execute(
            select(League)
            .join(Team, Team.league_id == League.id)
            .where(League.id == league_id, Team.user_id == user.id)
        )
        .scalars()
        .first()
    )
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    return league


def _find_users_team_key(user_teams: list[UserTeamInfo], league_key: str) -> str | None:
    for team in user_teams:
        if team.league_key == league_key:
            return team.team_key
    return None


def _sync_league_and_link(
    db: Session, client: YahooClient, league: League, users_team_key: str | None, user_id: int
) -> None:
    """Refresh one league's detail, claim the user's Team row, and map its rosters.

    league_sync.py stays owner-agnostic (a controller decision from Task 9/10) --
    claiming Team.user_id for the signed-in user is this route layer's job, done
    right here rather than inside sync_league_detail.
    """
    sync_league_detail(db, client, league.id, users_team_key=users_team_key)
    db.flush()

    if users_team_key is not None:
        team_row = db.execute(
            select(Team).where(Team.yahoo_team_key == users_team_key)
        ).scalar_one_or_none()
        if team_row is not None:
            team_row.user_id = user_id

    # map every team's roster in this league, not just the user's own -- the
    # build-profile population/roster lookups on GET /team need every rostered
    # player's yahoo_player_key -> NbaPlayer link to already exist
    team_ids = db.execute(select(Team.id).where(Team.league_id == league.id)).scalars().all()
    if team_ids:
        slots = db.execute(
            select(RosterSlot).where(RosterSlot.team_id.in_(team_ids))
        ).scalars().all()
        map_yahoo_players(
            db, [_RosterPlayerAdapter(player_key=s.yahoo_player_key, name=s.player_name) for s in slots]
        )
    db.flush()


def _round2(value: float) -> float:
    # +0.0 normalizes IEEE754 -0.0 (e.g. round(-0.0, 2)) to plain 0.0 so it
    # never leaks into a JSON response as a confusing "-0"
    return round(value, 2) + 0.0


# --- GET /api/me ---


@router.get("/api/me")
def get_me(user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    return {
        "display_name": user.display_name,
        "leagues": [_league_dict(league) for league in _linked_leagues(db, user)],
    }


# --- POST /api/sync ---


@router.post("/api/sync")
def sync_leagues(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
    client: YahooClient = Depends(get_yahoo_client),
) -> list[dict]:
    try:
        leagues = sync_user_leagues(db, client, user.id)
        db.flush()
        user_teams = client.get_user_teams()
        for league in leagues:
            users_team_key = _find_users_team_key(user_teams, league.yahoo_league_key)
            _sync_league_and_link(db, client, league, users_team_key, user.id)
    except YahooAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="yahoo_reauth_required"
        ) from exc
    except YahooUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="yahoo_unavailable"
        ) from exc

    # frontend/lib/api.ts's syncLeagues() expects League[] directly, not the
    # wrapped MeResponse shape -- return this user's now-linked leagues bare
    return [_league_dict(league) for league in _linked_leagues(db, user)]


# --- GET /api/leagues/{league_id}/overview ---


@router.get("/api/leagues/{league_id}/overview")
def league_overview(
    league_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
    client: YahooClient = Depends(get_yahoo_client),
) -> dict:
    league = _get_owned_league(db, user, league_id)

    standings_rows = db.execute(
        select(Standing, Team)
        .join(Team, Standing.team_id == Team.id)
        .where(Standing.league_id == league.id)
        .order_by(Standing.rank)
    ).all()
    standings = [
        {
            "team_id": team.id,
            "name": team.name,
            "rank": standing.rank,
            "wins": standing.wins,
            "losses": standing.losses,
            "ties": standing.ties,
        }
        for standing, team in standings_rows
    ]

    users_team = db.execute(
        select(Team).where(Team.league_id == league.id, Team.user_id == user.id)
    ).scalar_one_or_none()

    matchup: dict | None = None
    stale = False
    try:
        matchups = client.get_scoreboard(league.yahoo_league_key, week=None)
    except YahooUnavailableError:
        # live scoreboard couldn't be fetched (and no parsed payload to fall back
        # on) -- surface the DB-backed standings anyway, flagged stale, rather
        # than failing the whole overview
        stale = True
    except YahooAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="yahoo_reauth_required"
        ) from exc
    else:
        if users_team is not None:
            for m in matchups:
                team_keys = {t.team_key for t in m.teams}
                if users_team.yahoo_team_key in team_keys:
                    matchup = {
                        "week": m.week,
                        "teams": [
                            {"name": t.name, "category_totals": t.category_totals} for t in m.teams
                        ],
                    }
                    break

    return {
        "standings": standings,
        "matchup": matchup,
        "stale": stale,
        "synced_at": league.synced_at.isoformat(),
    }


# --- GET /api/leagues/{league_id}/team ---


@router.get("/api/leagues/{league_id}/team")
def league_team(
    league_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict:
    league = _get_owned_league(db, user, league_id)

    team = db.execute(
        select(Team).where(Team.league_id == league.id, Team.user_id == user.id)
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    slots = db.execute(select(RosterSlot).where(RosterSlot.team_id == team.id)).scalars().all()

    id_maps_by_key = {
        row.yahoo_player_key: row
        for row in db.execute(
            select(PlayerIdMap).where(
                PlayerIdMap.yahoo_player_key.in_([s.yahoo_player_key for s in slots])
            )
        )
        .scalars()
        .all()
    }
    nba_player_ids = {m.nba_player_id for m in id_maps_by_key.values() if m.nba_player_id is not None}
    nba_players_by_id = {
        p.id: p
        for p in (
            db.execute(select(NbaPlayer).where(NbaPlayer.id.in_(nba_player_ids))).scalars().all()
            if nba_player_ids
            else []
        )
    }

    current_season = get_settings().current_season
    season_avgs_by_player = {
        row.nba_player_id: row
        for row in (
            db.execute(
                select(PlayerSeasonAverage).where(
                    PlayerSeasonAverage.nba_player_id.in_(nba_player_ids),
                    PlayerSeasonAverage.season == current_season,
                )
            )
            .scalars()
            .all()
            if nba_player_ids
            else []
        )
    }

    roster_out = []
    for slot in slots:
        id_map = id_maps_by_key.get(slot.yahoo_player_key)
        nba_player = (
            nba_players_by_id.get(id_map.nba_player_id)
            if id_map is not None and id_map.nba_player_id is not None
            else None
        )
        season_avg = (
            season_avgs_by_player.get(id_map.nba_player_id)
            if id_map is not None and id_map.nba_player_id is not None
            else None
        )

        headshot_url = (
            _HEADSHOT_URL_TEMPLATE.format(nba_person_id=nba_player.nba_person_id)
            if nba_player is not None
            else None
        )

        averages_out = None
        if season_avg is not None:
            averages_out = {
                "fg_pct": round(season_avg.fgm / season_avg.fga, 3) if season_avg.fga else 0.0,
                "ft_pct": round(season_avg.ftm / season_avg.fta, 3) if season_avg.fta else 0.0,
                "tpm": round(season_avg.tpm, 1),
                "pts": round(season_avg.pts, 1),
                "reb": round(season_avg.reb, 1),
                "ast": round(season_avg.ast, 1),
                "stl": round(season_avg.stl, 1),
                "blk": round(season_avg.blk, 1),
                "tov": round(season_avg.tov, 1),
            }

        roster_out.append(
            {
                "yahoo_player_key": slot.yahoo_player_key,
                "name": slot.player_name,
                "position": slot.position,
                "injury_status": slot.injury_status,
                "headshot_url": headshot_url,
                "averages": averages_out,
            }
        )

    # population = every player with a current-season average, not just this
    # roster -- z-scores are only meaningful relative to the full player pool
    population_rows = db.execute(
        select(PlayerSeasonAverage).where(PlayerSeasonAverage.season == current_season)
    ).scalars().all()
    population = [
        PlayerAverages(
            player_key=str(row.nba_player_id),
            games=row.games_played,
            fgm=row.fgm,
            fga=row.fga,
            ftm=row.ftm,
            fta=row.fta,
            tpm=row.tpm,
            pts=row.pts,
            reb=row.reb,
            ast=row.ast,
            stl=row.stl,
            blk=row.blk,
            tov=row.tov,
        )
        for row in population_rows
    ]
    all_zscores = compute_player_zscores(population)

    roster_zscores = []
    for slot in slots:
        id_map = id_maps_by_key.get(slot.yahoo_player_key)
        if id_map is not None and id_map.nba_player_id is not None:
            z = all_zscores.get(str(id_map.nba_player_id))
            if z is not None:
                roster_zscores.append(z)

    profile = compute_team_profile(roster_zscores)
    mapped_count = len(roster_zscores)
    means = {
        cat: _round2((profile["totals"][cat] / mapped_count) if mapped_count else 0.0)
        for cat in CATEGORIES
    }
    totals = {cat: _round2(profile["totals"][cat]) for cat in CATEGORIES}

    # this endpoint reads only the DB (the live scoreboard call is /overview's
    # job) -- "stale" only reflects whether the league has ever been synced at all
    stale = league.synced_at is None
    synced_at = (
        league.synced_at.isoformat() if league.synced_at is not None else datetime.now(timezone.utc).isoformat()
    )

    return {
        "roster": roster_out,
        "build_profile": {"totals": totals, "labels": profile["labels"], "means": means},
        "stale": stale,
        "synced_at": synced_at,
    }


# --- POST /api/leagues/{league_id}/refresh ---


@router.post("/api/leagues/{league_id}/refresh", status_code=status.HTTP_204_NO_CONTENT)
def refresh_league(
    league_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
    client: YahooClient = Depends(get_yahoo_client),
) -> Response:
    league = _get_owned_league(db, user, league_id)
    try:
        user_teams = client.get_user_teams()
        users_team_key = _find_users_team_key(user_teams, league.yahoo_league_key)
        _sync_league_and_link(db, client, league, users_team_key, user.id)
    except YahooAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="yahoo_reauth_required"
        ) from exc
    except YahooUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="yahoo_unavailable"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- POST /api/account/disconnect ---


@router.post("/api/account/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_account(
    user: User = Depends(current_user), db: Session = Depends(get_session)
) -> Response:
    db.execute(delete(YahooToken).where(YahooToken.user_id == user.id))
    db.flush()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    # disconnecting Yahoo revokes the session too -- there's nothing left to
    # show without a token, so force a fresh login/reconnect
    response.delete_cookie(key=SESSION_COOKIE_NAME, httponly=True, secure=True, samesite="lax")
    return response


# --- DELETE /api/account ---


@router.delete("/api/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_session)) -> Response:
    # FK cascades (ondelete=CASCADE on yahoo_tokens/yahoo_api_cache, SET NULL on
    # teams.user_id) do the rest of the cleanup at the db level
    db.execute(delete(User).where(User.id == user.id))
    db.flush()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(key=SESSION_COOKIE_NAME, httponly=True, secure=True, samesite="lax")
    return response
