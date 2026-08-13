"""Dashboard API: wires auth, sync, warehouse, and the engine into the JSON
API frontend/lib/api.ts consumes.

Every response shape here must match frontend/lib/api.ts's TypeScript
interfaces exactly (field-for-field) -- that file, not this module's own
judgment, is the source of truth for what the frontend expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ninecat.auth.sessions import SESSION_COOKIE_NAME, current_user
from ninecat.config import get_settings
from ninecat.db import get_session
from ninecat.engine import (
    CATEGORIES,
    DEFAULT_ROSTER_SLOTS,
    SLOT_CLASSES,
    DraftPoolPlayer,
    LeagueConfig,
    PlayerAverages,
    compute_draft_values,
    compute_player_zscores,
    compute_team_profile,
    recommend_picks,
    suggest_punt_builds,
)
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


# --- Draft board / recommend shared helpers ---


@dataclass(frozen=True)
class _DraftableRow:
    """One draftable player's resolved stat line (projection wins over season
    average, D2) plus the display metadata the board/recommend responses need."""

    nba_player: NbaPlayer
    projected_games: float
    source_label: str  # "projection" | "season_average"
    fgm: float
    fga: float
    ftm: float
    fta: float
    tpm: float
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    tov: float


def _resolve_projection_source(db: Session, season: str, source: str | None) -> str | None:
    """Which PlayerProjection.source to value the pool with: the explicit
    query/body param if given (validated against what actually exists), the
    only source present for this season, or None (pure season-average board)
    if no projections exist yet at all. Ambiguous with no explicit choice, or
    an explicit choice that doesn't exist -> 400 naming the real choices,
    rather than silently picking one or silently degrading to a mislabeled
    season-average board (plan D2)."""
    sources = sorted(
        db.execute(
            select(PlayerProjection.source).where(PlayerProjection.season == season).distinct()
        )
        .scalars()
        .all()
    )
    if source is not None:
        if source not in sources:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown projection source {source!r} for {season}, valid sources: {sources}",
            )
        return source
    if len(sources) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"multiple projection sources available for {season}, pass ?source=: {sources}",
        )
    return sources[0] if sources else None


def _draftable_rows(db: Session, season: str, source: str | None) -> dict[int, _DraftableRow]:
    """Every NbaPlayer with a `source` projection or a season average for
    `season`, keyed by nba_player_id -- independent of roster status, since a
    rostered player's own stat row is still needed to z-score their
    contribution to punt suggestions. Callers exclude rostered ids separately."""
    projections_by_player: dict[int, PlayerProjection] = {}
    if source is not None:
        projections_by_player = {
            row.nba_player_id: row
            for row in db.execute(
                select(PlayerProjection).where(
                    PlayerProjection.season == season, PlayerProjection.source == source
                )
            )
            .scalars()
            .all()
        }
    season_avgs_by_player = {
        row.nba_player_id: row
        for row in db.execute(
            select(PlayerSeasonAverage).where(PlayerSeasonAverage.season == season)
        )
        .scalars()
        .all()
    }
    candidate_ids = set(projections_by_player) | set(season_avgs_by_player)
    if not candidate_ids:
        return {}

    nba_players_by_id = {
        p.id: p
        for p in db.execute(select(NbaPlayer).where(NbaPlayer.id.in_(candidate_ids))).scalars().all()
    }

    rows: dict[int, _DraftableRow] = {}
    for player_id in candidate_ids:
        nba_player = nba_players_by_id.get(player_id)
        if nba_player is None:
            continue
        projection = projections_by_player.get(player_id)
        season_avg = season_avgs_by_player.get(player_id)
        # projection wins over season average when both exist (D2 fallback)
        stat_row = projection if projection is not None else season_avg
        rows[player_id] = _DraftableRow(
            nba_player=nba_player,
            projected_games=float(
                projection.projected_games if projection is not None else season_avg.games_played
            ),
            source_label="projection" if projection is not None else "season_average",
            fgm=stat_row.fgm,
            fga=stat_row.fga,
            ftm=stat_row.ftm,
            fta=stat_row.fta,
            tpm=stat_row.tpm,
            pts=stat_row.pts,
            reb=stat_row.reb,
            ast=stat_row.ast,
            stl=stat_row.stl,
            blk=stat_row.blk,
            tov=stat_row.tov,
        )
    return rows


def _zscores_for(rows: dict[int, _DraftableRow]) -> dict[str, dict[str, float]]:
    # one shared population for the whole draftable universe (mirrors /team's
    # population-then-subset pattern) -- both the board's pool and a caller's
    # own roster (needed for punt suggestions) draw from the same z's, so
    # they're on the same scale
    population = [
        PlayerAverages(
            player_key=str(player_id),
            games=row.projected_games,
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
        for player_id, row in rows.items()
    ]
    return compute_player_zscores(population)


def _draft_pool_player(
    player_id: int, row: _DraftableRow, zscores: dict[str, dict[str, float]]
) -> DraftPoolPlayer:
    return DraftPoolPlayer(
        player_key=str(player_id),
        position=row.nba_player.position,
        projected_games=row.projected_games,
        zscores=zscores[str(player_id)],
    )


def _league_rostered_player_ids(db: Session, league: League) -> set[int]:
    """nba_player_id set for every player rostered on ANY team in this league
    -- excluded from the draftable pool, they're already taken."""
    team_ids = select(Team.id).where(Team.league_id == league.id)
    rostered_keys = select(RosterSlot.yahoo_player_key).where(RosterSlot.team_id.in_(team_ids))
    return set(
        db.execute(
            select(PlayerIdMap.nba_player_id).where(
                PlayerIdMap.yahoo_player_key.in_(rostered_keys),
                PlayerIdMap.nba_player_id.is_not(None),
            )
        )
        .scalars()
        .all()
    )


def _my_team_rostered_player_ids(db: Session, league: League, user: User) -> set[int]:
    """nba_player_id set for the signed-in user's own team in this league --
    the basis for the board's punt suggestions. Empty (not 404) when the user
    has no claimed team here, since a board can still be viewed unclaimed."""
    my_team_id = db.execute(
        select(Team.id).where(Team.league_id == league.id, Team.user_id == user.id)
    ).scalar_one_or_none()
    if my_team_id is None:
        return set()
    rostered_keys = select(RosterSlot.yahoo_player_key).where(RosterSlot.team_id == my_team_id)
    return set(
        db.execute(
            select(PlayerIdMap.nba_player_id).where(
                PlayerIdMap.yahoo_player_key.in_(rostered_keys),
                PlayerIdMap.nba_player_id.is_not(None),
            )
        )
        .scalars()
        .all()
    )


def _parsed_roster_slots(raw_positions: object) -> tuple[tuple[str, int], ...] | None:
    """Best-effort parse of settings_json.roster_positions into
    LeagueConfig.roster_slots; None on any malformed shape (wrong dict keys,
    a non-dict entry, a non-numeric count, ...) rather than raising -- a
    warehouse data-shape issue on this field must fall back to
    DEFAULT_ROSTER_SLOTS, not 500 the caller."""
    try:
        return tuple((rp.get("position"), int(rp.get("count", 0) or 0)) for rp in raw_positions)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _league_config(league: League) -> LeagueConfig:
    """Build a LeagueConfig from League.settings_json, tolerant of a
    never-synced league (settings_json == {}), a malformed roster_positions
    shape, and a roster layout that recognizes zero starter slots --
    compute_draft_values raises ValueError on the last of those, and none of
    the three may ever reach the client as a 500."""
    num_teams = league.num_teams if league.num_teams and league.num_teams >= 1 else 12
    raw_positions = league.settings_json.get("roster_positions") if league.settings_json else None
    roster_slots = _parsed_roster_slots(raw_positions) if raw_positions else None
    if not roster_slots or not any(
        name in SLOT_CLASSES and count > 0 for name, count in roster_slots
    ):
        roster_slots = DEFAULT_ROSTER_SLOTS
    return LeagueConfig(num_teams=num_teams, roster_slots=roster_slots)


def _validate_punt_categories(punt: list[str]) -> None:
    """400 on an unknown ?punt=/body.punt category name, naming it -- a
    caller/client bug, not a server error. Once this passes, `punt` is a
    valid frozenset[str] subset of CATEGORIES, so the engine's own
    unknown-category ValueError can never fire; any ValueError past this
    point is a genuine engine bug and should surface as a 500, not be
    silently downgraded to a 400 with engine-internal prose."""
    unknown = sorted(set(punt) - set(CATEGORIES))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"unknown punt category: {unknown}"
        )


def _league_stale_and_synced_at(league: League) -> tuple[bool, str]:
    stale = league.synced_at is None
    synced_at = (
        league.synced_at.isoformat()
        if league.synced_at is not None
        else datetime.now(timezone.utc).isoformat()
    )
    return stale, synced_at


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
        # lets the frontend highlight the caller's own row without guessing from
        # matchup order (which team appears first isn't a reliable signal)
        "my_team_id": users_team.id if users_team is not None else None,
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
    stale, synced_at = _league_stale_and_synced_at(league)

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


# --- GET /api/leagues/{league_id}/draft/board ---


@router.get("/api/leagues/{league_id}/draft/board")
def draft_board(
    league_id: int,
    source: str | None = None,
    punt: list[str] = Query(default=[]),
    my_player_key: list[str] = Query(default=[]),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    league = _get_owned_league(db, user, league_id)
    season = get_settings().current_season
    resolved_source = _resolve_projection_source(db, season, source)

    rows = _draftable_rows(db, season, resolved_source)
    zscores = _zscores_for(rows)

    # ?my_player_key= lets a mock draft (Yahoo roster still empty pre-draft)
    # supply the punt advisor's roster basis instead -- validated against the
    # same draftable universe /draft/recommend uses for my_player_keys
    unknown_keys = sorted({k for k in my_player_key if not k.isdigit() or int(k) not in rows})
    if unknown_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"unknown player keys: {unknown_keys}"
        )

    league_rostered = _league_rostered_player_ids(db, league)
    my_rostered = (
        {int(k) for k in my_player_key}
        if my_player_key
        else _my_team_rostered_player_ids(db, league, user)
    )

    pool_by_id = {
        pid: _draft_pool_player(pid, row, zscores)
        for pid, row in rows.items()
        if pid not in league_rostered
    }
    my_players = [
        _draft_pool_player(pid, rows[pid], zscores) for pid in my_rostered if pid in rows
    ]

    _validate_punt_categories(punt)
    config = _league_config(league)
    values = compute_draft_values(list(pool_by_id.values()), config, punt=frozenset(punt))

    players_out = [
        {
            "player_key": p.player_key,
            "name": rows[pid].nba_player.full_name,
            "position": p.position,
            "nba_person_id": rows[pid].nba_player.nba_person_id,
            "headshot_url": _HEADSHOT_URL_TEMPLATE.format(
                nba_person_id=rows[pid].nba_player.nba_person_id
            ),
            "best_class": values[p.player_key].best_class,
            "projected_games": p.projected_games,
            "base": _round2(values[p.player_key].base),
            "vorp": _round2(values[p.player_key].vorp),
            "value": _round2(values[p.player_key].value),
            "replacement": _round2(values[p.player_key].replacement),
            "zscores": {cat: _round2(p.zscores[cat]) for cat in CATEGORIES},
            # "projection" | "season_average" -- distinct from the top-level
            # `source` field (the projection SOURCE NAME), see I4
            "stat_basis": rows[pid].source_label,
        }
        for pid, p in pool_by_id.items()
    ]
    # value desc; player_key tie-break keeps ordering deterministic
    players_out.sort(key=lambda x: (-x["value"], x["player_key"]))

    # punt suggestions are built from my_rostered (Yahoo roster, or the
    # ?my_player_key= override above) -- never from the ?punt= re-ranking param;
    # an empty roster has no basis for a suggestion, so it returns [] rather
    # than suggesting off the pool alone
    punt_suggestions_out = []
    if my_players:
        for s in suggest_punt_builds(my_players, list(pool_by_id.values()), config):
            punt_suggestions_out.append(
                {
                    # punt is a frozenset (hash-order iteration) -- punt_ordered is
                    # the stable CATEGORIES-order tuple; only that ever gets serialized
                    "punt": list(s.punt_ordered),
                    "score": _round2(s.score),
                    "improvement": _round2(s.improvement),
                    "pool_delta": _round2(s.pool_delta),
                    "weakest": s.weakest,
                    "weakest_mean": _round2(s.weakest_mean),
                    "rationale": s.rationale,
                }
            )

    stale, synced_at = _league_stale_and_synced_at(league)
    return {
        "players": players_out,
        "punt_suggestions": punt_suggestions_out,
        "source": resolved_source,
        "stale": stale,
        "synced_at": synced_at,
    }


# --- POST /api/leagues/{league_id}/draft/recommend ---


class DraftRecommendRequest(BaseModel):
    my_player_keys: list[str] = []
    taken_player_keys: list[str] = []
    overall_pick: int
    punt: list[str] = []
    limit: int = 5
    source: str | None = None


@router.post("/api/leagues/{league_id}/draft/recommend")
def draft_recommend(
    league_id: int,
    body: DraftRecommendRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    league = _get_owned_league(db, user, league_id)

    if body.overall_pick < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="overall_pick must be >= 1"
        )
    if not (1 <= body.limit <= 50):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="limit must be between 1 and 50"
        )

    season = get_settings().current_season
    resolved_source = _resolve_projection_source(db, season, body.source)
    rows = _draftable_rows(db, season, resolved_source)

    requested_keys = [*body.my_player_keys, *body.taken_player_keys]
    unknown_keys = sorted({k for k in requested_keys if not k.isdigit() or int(k) not in rows})
    if unknown_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"unknown player keys: {unknown_keys}"
        )

    zscores = _zscores_for(rows)
    league_rostered = _league_rostered_player_ids(db, league)
    my_keys = set(body.my_player_keys)
    taken_keys = set(body.taken_player_keys)

    available_players = [
        _draft_pool_player(pid, row, zscores)
        for pid, row in rows.items()
        if pid not in league_rostered and str(pid) not in my_keys and str(pid) not in taken_keys
    ]
    my_players = [_draft_pool_player(int(k), rows[int(k)], zscores) for k in body.my_player_keys]

    _validate_punt_categories(body.punt)
    config = _league_config(league)
    recs = recommend_picks(
        my_players,
        available_players,
        config,
        body.overall_pick,
        punt=frozenset(body.punt),
        limit=body.limit,
    )

    recommendations = [
        {
            "player_key": r.player_key,
            "name": rows[int(r.player_key)].nba_player.full_name,
            "position": rows[int(r.player_key)].nba_player.position,
            "value": _round2(r.value),
            "rank_score": _round2(r.rank_score),
            "reasons": list(r.reasons),
            "need_cats": list(r.need_cats),
        }
        for r in recs
    ]

    stale, synced_at = _league_stale_and_synced_at(league)
    return {"recommendations": recommendations, "stale": stale, "synced_at": synced_at}
