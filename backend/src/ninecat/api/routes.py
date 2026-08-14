"""Dashboard API: wires auth, sync, warehouse, and the engine into the JSON
API frontend/lib/api.ts consumes.

Every response shape here must match frontend/lib/api.ts's TypeScript
interfaces exactly (field-for-field) -- that file, not this module's own
judgment, is the source of truth for what the frontend expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ninecat.advisor import (
    FEATURE_ADDS,
    FEATURE_DRAFT,
    FEATURE_MATCHUP,
    FEATURE_TRADES,
    AdvisorClient,
    AdvisorOutcome,
    AdvisorRequest,
    ShortlistItem,
    build_advisor_client,
    explain,
)
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
    RosterPlayer,
    StreamCandidate,
    WaiverCandidate,
    WeeklyPlayerRate,
    WeeklyProjection,
    compare_matchup,
    compare_rosters,
    compute_draft_values,
    compute_player_zscores,
    compute_team_profile,
    evaluate_trades,
    generate_trade_candidates,
    plan_streaming,
    project_week,
    recommend_picks,
    score_waiver_candidates,
    suggest_punt_builds,
)
from ninecat.models import (
    FantasyWeek,
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
    YahooToken,
)
from ninecat.sync.league_sync import sync_league_detail, sync_user_leagues
from ninecat.warehouse.fantasy_weeks import resolve_week, week_date_range
from ninecat.warehouse.id_mapping import map_yahoo_players
from ninecat.warehouse.nba_schedule import games_in_range
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


def get_advisor_client() -> AdvisorClient | None:
    """FastAPI dependency yielding the Claude advisor client, or None when no
    key is configured.

    None is a first-class mode, not an error (plan A2) -- it is what every test
    and every key-less deployment runs on. Overridden in tests with a fake, the
    same seam get_yahoo_client uses, so no test can reach the network.
    """
    return build_advisor_client(get_settings())


def _explanations_out(outcome: AdvisorOutcome) -> dict:
    """The advisor half of a feature response. Shared by all four features so
    the frontend has one shape to render (plan B3).

    `explanations_reason` is a structured token, never prose -- the frontend
    owns the wording (see components/dashboard/advisor/tokens.ts).
    """
    if outcome.result is None:
        return {
            "explanations": None,
            "explanations_available": False,
            "explanations_reason": outcome.reason,
        }
    return {
        "explanations": {
            # visible model attribution is not optional: the user must be able
            # to tell which parts are arithmetic and which are judgement (A6)
            "model": outcome.result.model,
            "summary": outcome.result.summary,
            "ranked": [
                {"item_key": e.item_key, "reasoning": e.reasoning}
                for e in outcome.result.ranked
            ],
        },
        "explanations_available": True,
        "explanations_reason": None,
    }


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


# How many of each engine's ranked rows are handed to the advisor. Each
# endpoint's own `limit` goes much higher, but the decision the user is
# actually making is between the top few, and prompt size (and therefore cost)
# scales with this. Per-feature rather than one shared number because the lists
# differ in kind: a streaming plan is already short, trade proposals are long
# to describe, and a draft board is neither.
DRAFT_ADVISOR_SHORTLIST_MAX = 5
ADDS_ADVISOR_SHORTLIST_MAX = 6
MATCHUP_ADVISOR_SHORTLIST_MAX = 5
TRADES_ADVISOR_SHORTLIST_MAX = 4


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
    advisor: AdvisorClient | None = Depends(get_advisor_client),
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

    settings = get_settings()
    season = settings.current_season
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

    # exactly one advisor call per request, whatever `limit` is -- the mock
    # draft hits this endpoint once per user turn, so per-request fan-out here
    # would multiply straight into per-draft cost
    outcome = explain(
        db,
        _draft_advisor_request(body, config, recommendations, my_players, rows, resolved_source),
        client=advisor,
        model=settings.anthropic_model,
    )

    stale, synced_at = _league_stale_and_synced_at(league)
    return {
        "recommendations": recommendations,
        **_explanations_out(outcome),
        "stale": stale,
        "synced_at": synced_at,
    }


def _draft_advisor_request(
    body: DraftRecommendRequest,
    config: LeagueConfig,
    recommendations: list[dict],
    my_players: list[DraftPoolPlayer],
    rows: dict[int, _DraftableRow],
    resolved_source: str | None,
) -> AdvisorRequest:
    """Shape the draft shortlist for the advisor.

    Everything here is data the page already shows the user -- player names,
    stat-derived numbers, the engine's own reasons, the punts they picked.
    Nothing user-scoped goes in: no user id, no email, no Yahoo token, no league
    or team name (plan A4, pinned by the no-secrets test).
    """
    shortlist = tuple(
        ShortlistItem(
            item_key=r["player_key"],
            label=r["name"],
            detail=r["position"],
            metrics={"value": r["value"], "rank_score": r["rank_score"]},
            tags=tuple(r["reasons"])
            + ((f"helps {', '.join(r['need_cats'])}",) if r["need_cats"] else ()),
        )
        for r in recommendations[:DRAFT_ADVISOR_SHORTLIST_MAX]
    )
    # both of these are sorted into a canonical order rather than left in
    # request order: neither ordering carries meaning, and leaving it to the
    # caller would make the same question hash two different ways and miss the
    # cache (punt uses CATEGORIES order, the same canonical order the rest of
    # the codebase serializes punts in)
    punting = [c for c in CATEGORIES if c in set(body.punt)]
    roster = sorted(rows[int(p.player_key)].nba_player.full_name for p in my_players)
    return AdvisorRequest(
        feature=FEATURE_DRAFT,
        situation=f"pick {body.overall_pick} overall in a {config.num_teams}-team 9-cat league",
        context={
            "punting": ", ".join(punting) if punting else "nothing",
            "roster so far": ", ".join(roster) if roster else "empty",
            "stat basis": resolved_source or "last season's averages",
        },
        shortlist=shortlist,
    )


# --- GET /api/leagues/{league_id}/matchup ---

# opponent_reason tokens -- structured contract keys, never English prose (the
# engine-emitting-prose finding hit two earlier tasks; this route inherits the
# same discipline for its own reason field)
OPPONENT_REASON_YAHOO_UNAVAILABLE = "yahoo_unavailable"
OPPONENT_REASON_NO_MATCHUP = "no_matchup_this_week"
OPPONENT_REASON_SINGLE_TEAM_MATCHUP = "no_opponent_in_matchup"
OPPONENT_REASON_TEAM_NOT_SYNCED = "opponent_team_not_synced"

# streaming.window_basis -- tells the UI whether the plan covers the
# remaining days of a live week (as_of falls inside the week) or the whole
# week of a past/future one (as_of clamped because it fell outside the
# range), so a full-week plan is never presented as adds still actionable today
STREAM_WINDOW_REMAINING = "remaining"
STREAM_WINDOW_FULL_WEEK = "full_week"


def _fallback_week(db: Session, league: League) -> int:
    """The week to project when ?week= is omitted and the live scoreboard
    couldn't identify a "current" week either (Yahoo unavailable, off-season,
    or no matchup found for this team this call): the highest week already
    resolved for this league, or week 1 if none ever has been. Deliberately
    not date.today()-based -- FantasyWeek rows are the only record this
    endpoint has of "what week were we last tracking."
    """
    latest = db.execute(
        select(func.max(FantasyWeek.week)).where(FantasyWeek.league_id == league.id)
    ).scalar_one()
    return latest if latest is not None else 1


def _league_max_weekly_adds(league: League) -> int:
    """league.settings_json's max_weekly_adds, tolerant of a never-synced
    league or a malformed value. Falls back to 0 (not a guessed default) so a
    missing/bad budget surfaces honestly through plan_streaming's own
    "no_adds_available" note rather than silently driving a fabricated plan.
    """
    raw = league.settings_json.get("max_weekly_adds") if league.settings_json else None
    return raw if isinstance(raw, int) and raw > 0 else 0


def _nba_team_id_maps(db: Session) -> tuple[dict[str, int], dict[int, int]]:
    """abbreviation -> NBA.com team id, and internal NbaTeam PK -> NBA.com team
    id. games_in_range keys off NBA.com's own id, not our internal NbaTeam.id,
    so both the roster-slot-abbreviation path and the NbaPlayer.nba_team_id
    fallback path need a translation step; built once per request since the
    table is small (30ish rows) and every player lookup needs it.
    """
    teams = db.execute(select(NbaTeam)).scalars().all()
    return (
        {t.abbreviation: t.nba_team_id for t in teams},
        {t.id: t.nba_team_id for t in teams},
    )


def _resolve_roster_nba_team_id(
    slot: RosterSlot,
    nba_player: NbaPlayer | None,
    abbr_to_nba_id: dict[str, int],
    internal_id_to_nba_id: dict[int, int],
) -> int | None:
    """RosterSlot.nba_team_abbr first (direct, Yahoo-sourced on every roster
    entry), falling back to the PlayerIdMap -> NbaPlayer -> NbaTeam chain
    (best-effort name matching) -- the abbreviation is a straight lookup while
    the id map can be wrong, stale, or simply absent (plan M2).
    """
    if slot.nba_team_abbr and slot.nba_team_abbr in abbr_to_nba_id:
        return abbr_to_nba_id[slot.nba_team_abbr]
    if nba_player is not None and nba_player.nba_team_id is not None:
        return internal_id_to_nba_id.get(nba_player.nba_team_id)
    return None


def _team_side(
    db: Session,
    team: Team,
    rows: dict[int, _DraftableRow],
    zscores: dict[str, dict[str, float]],
    abbr_to_nba_id: dict[str, int],
    internal_id_to_nba_id: dict[int, int],
    week_start: date,
    week_end: date,
) -> dict:
    """One roster's raw weekly projection + build profile (unrounded -- the
    caller rounds only at JSON-serialization time via _side_out, since
    compare_matchup must run on real totals, not display-rounded ones).

    Per-player rates come from `rows` (projection-wins-over-season-average,
    the same source the draft board uses -- reused rather than re-queried).
    A rostered player absent from `rows` (no projection and no season average
    at all) contributes nothing; there is no stat basis to project them on,
    the same skip the draft board applies.
    """
    slots = db.execute(select(RosterSlot).where(RosterSlot.team_id == team.id)).scalars().all()
    id_maps_by_key = (
        {
            m.yahoo_player_key: m
            for m in db.execute(
                select(PlayerIdMap).where(
                    PlayerIdMap.yahoo_player_key.in_([s.yahoo_player_key for s in slots])
                )
            )
            .scalars()
            .all()
        }
        if slots
        else {}
    )

    player_rates: list[WeeklyPlayerRate] = []
    roster_zscores: list[dict[str, float]] = []
    for slot in slots:
        id_map = id_maps_by_key.get(slot.yahoo_player_key)
        nba_player_id = id_map.nba_player_id if id_map is not None else None
        row = rows.get(nba_player_id) if nba_player_id is not None else None
        if row is None:
            continue
        nba_team_id = _resolve_roster_nba_team_id(
            slot, row.nba_player, abbr_to_nba_id, internal_id_to_nba_id
        )
        games = (
            float(games_in_range(db, nba_team_id, week_start, week_end).count)
            if nba_team_id is not None
            else 0.0
        )
        player_rates.append(
            WeeklyPlayerRate(
                player_key=slot.yahoo_player_key,
                games=games,
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
        )
        z = zscores.get(str(nba_player_id))
        if z is not None:
            roster_zscores.append(z)

    return {
        "team_id": team.id,
        "team_key": team.yahoo_team_key,
        "name": team.name,
        "projection": project_week(player_rates),
        "build_profile": compute_team_profile(roster_zscores),
        "roster_size": len(roster_zscores),
        # per-player z's, not just the aggregated build_profile -- the adds
        # endpoint's need-weighting (score_waiver_candidates) needs a list of
        # per-player dicts, not a summed profile; _side_out ignores this key
        "roster_zscores": roster_zscores,
    }


def _side_out(side: dict) -> dict:
    """Round a _team_side result for the JSON response -- the only place
    display rounding happens, so every consumer of the raw dataclasses
    (compare_matchup, plan_streaming) still sees real totals.
    """
    projection: WeeklyProjection = side["projection"]
    profile = side["build_profile"]
    roster_size = side["roster_size"]
    means = {
        cat: _round2((profile["totals"][cat] / roster_size) if roster_size else 0.0)
        for cat in CATEGORIES
    }
    return {
        "team_id": side["team_id"],
        "team_key": side["team_key"],
        "name": side["name"],
        "projection": {
            "totals": {cat: _round2(projection.totals[cat]) for cat in CATEGORIES},
            "components": {k: _round2(v) for k, v in projection.components.items()},
            "games": _round2(projection.games),
            "player_games": {k: _round2(v) for k, v in projection.player_games.items()},
        },
        "build_profile": {
            "totals": {cat: _round2(profile["totals"][cat]) for cat in CATEGORIES},
            "labels": profile["labels"],
            "means": means,
        },
    }


@dataclass(frozen=True)
class _CandidatePlayer:
    """One free agent's resolved schedule + raw per-game rates within a date
    window -- the shared basis for both the streaming optimizer
    (StreamCandidate, needs the game DATES for day-by-day planning) and the
    waiver ranker (WaiverCandidate, needs a games COUNT and stat_basis).
    Generalized here rather than forked so both endpoints draw candidates
    from the identical league-wide-unrostered universe with identical rates.
    """

    player_id: int
    game_dates: tuple[date, ...]
    category_rates: dict[str, float]
    stat_basis: str


def _candidate_players(
    db: Session,
    rows: dict[int, _DraftableRow],
    league_rostered: set[int],
    internal_id_to_nba_id: dict[int, int],
    start_day: date,
    end_day: date,
) -> list[_CandidatePlayer]:
    """Free-agent pool within [start_day, end_day]: every draftable player not
    rostered anywhere in the league (mirrors the draft board's own
    league-wide rostered exclusion), with RAW per-game rates -- callers
    (plan_streaming, score_waiver_candidates) own turning a rate into a
    signed value, per their own module docstrings on the tov convention. A
    player whose NBA team can't be resolved, or who has no games left in the
    window, is not a useful candidate and is dropped here rather than passed
    through as a dead entry.
    """
    candidates: list[_CandidatePlayer] = []
    for player_id, row in rows.items():
        if player_id in league_rostered:
            continue
        nba_team_id = (
            internal_id_to_nba_id.get(row.nba_player.nba_team_id)
            if row.nba_player.nba_team_id is not None
            else None
        )
        if nba_team_id is None:
            continue
        game_dates = tuple(games_in_range(db, nba_team_id, start_day, end_day).dates)
        if not game_dates:
            continue
        candidates.append(
            _CandidatePlayer(
                player_id=player_id,
                game_dates=game_dates,
                category_rates={
                    "fg_pct": row.fgm / row.fga if row.fga else 0.0,
                    "ft_pct": row.ftm / row.fta if row.fta else 0.0,
                    "tpm": row.tpm,
                    "pts": row.pts,
                    "reb": row.reb,
                    "ast": row.ast,
                    "stl": row.stl,
                    "blk": row.blk,
                    "tov": row.tov,
                },
                stat_basis=row.source_label,
            )
        )
    return candidates


def _streaming_candidates(
    db: Session,
    rows: dict[int, _DraftableRow],
    league_rostered: set[int],
    internal_id_to_nba_id: dict[int, int],
    start_day: date,
    end_day: date,
) -> list[StreamCandidate]:
    """The matchup endpoint's add-schedule optimizer input -- see
    _candidate_players for the shared free-agent universe/rate computation."""
    return [
        StreamCandidate(
            player_key=str(c.player_id), game_dates=c.game_dates, category_rates=c.category_rates
        )
        for c in _candidate_players(db, rows, league_rostered, internal_id_to_nba_id, start_day, end_day)
    ]


def _waiver_candidates(
    db: Session,
    rows: dict[int, _DraftableRow],
    league_rostered: set[int],
    internal_id_to_nba_id: dict[int, int],
    start_day: date,
    end_day: date,
) -> list[WaiverCandidate]:
    """The adds endpoint's waiver-ranker input -- see _candidate_players for
    the shared free-agent universe/rate computation. games_remaining is the
    count of games in the window (score_waiver_candidates only needs a
    count, unlike plan_streaming's day-by-day StreamCandidate)."""
    return [
        WaiverCandidate(
            player_key=str(c.player_id),
            games_remaining=float(len(c.game_dates)),
            rates=c.category_rates,
            stat_basis=c.stat_basis,
        )
        for c in _candidate_players(db, rows, league_rostered, internal_id_to_nba_id, start_day, end_day)
    ]


def _roster_players(
    db: Session, team: Team, rows: dict[int, _DraftableRow], zscores: dict[str, dict[str, float]]
) -> tuple[list[RosterPlayer], dict[str, dict]]:
    """A team's roster as RosterPlayer (the trade engines' input, keyed by
    yahoo_player_key -- unique per roster slot) plus a parallel display-info
    dict (name/position/headshot, keyed the same way) the trades response
    uses to resolve a verdict's give/get player_keys without a second roster
    walk -- mirrors the draft board's nba_person_id/headshot_url fields (D)
    so the page can render avatars the same way. A slot with no id-map link
    or no stat basis at all is skipped from both (same skip _team_side and
    the draft board apply) -- there is no z-score to compare it on.
    """
    slots = db.execute(select(RosterSlot).where(RosterSlot.team_id == team.id)).scalars().all()
    if not slots:
        return [], {}
    id_maps_by_key = {
        m.yahoo_player_key: m
        for m in db.execute(
            select(PlayerIdMap).where(
                PlayerIdMap.yahoo_player_key.in_([s.yahoo_player_key for s in slots])
            )
        )
        .scalars()
        .all()
    }
    players: list[RosterPlayer] = []
    info: dict[str, dict] = {}
    for slot in slots:
        id_map = id_maps_by_key.get(slot.yahoo_player_key)
        nba_player_id = id_map.nba_player_id if id_map is not None else None
        row = rows.get(nba_player_id) if nba_player_id is not None else None
        if row is None:
            continue
        z = zscores.get(str(nba_player_id))
        if z is None:
            continue
        players.append(RosterPlayer(player_key=slot.yahoo_player_key, zscores=z))
        info[slot.yahoo_player_key] = {
            "name": row.nba_player.full_name,
            "position": row.nba_player.position,
            "nba_person_id": row.nba_player.nba_person_id,
            "headshot_url": _HEADSHOT_URL_TEMPLATE.format(nba_person_id=row.nba_player.nba_person_id),
        }
    return players, info


def _resolve_week_and_opponent(
    db: Session, client: YahooClient, league: League, my_team: Team, week: int | None
):
    """Resolve the target fantasy week and this team's opponent from a single
    scoreboard call -- shared by /matchup and /adds so week resolution, date
    persistence, and opponent identification can never diverge between the
    two pages. Returns (target_week, week_range, opponent_team, opponent_reason).
    """
    scoreboard_unavailable = False
    try:
        matchups = client.get_scoreboard(league.yahoo_league_key, week=week)
    except YahooAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="yahoo_reauth_required"
        ) from exc
    except YahooUnavailableError:
        matchups = []
        scoreboard_unavailable = True

    my_matchup = next(
        (m for m in matchups if my_team.yahoo_team_key in {t.team_key for t in m.teams}), None
    )

    if week is not None:
        target_week = week
    elif my_matchup is not None:
        target_week = my_matchup.week
    else:
        target_week = _fallback_week(db, league)

    resolve_week(
        db,
        league,
        target_week,
        yahoo_start=my_matchup.week_start if my_matchup is not None else None,
        yahoo_end=my_matchup.week_end if my_matchup is not None else None,
    )
    week_range = week_date_range(db, league, target_week)
    assert week_range is not None  # resolve_week always leaves start/end populated

    opponent_team: Team | None = None
    opponent_reason: str | None = None
    if scoreboard_unavailable:
        opponent_reason = OPPONENT_REASON_YAHOO_UNAVAILABLE
    elif my_matchup is None:
        opponent_reason = OPPONENT_REASON_NO_MATCHUP
    else:
        opponent_keys = [
            t.team_key for t in my_matchup.teams if t.team_key != my_team.yahoo_team_key
        ]
        if not opponent_keys:
            opponent_reason = OPPONENT_REASON_SINGLE_TEAM_MATCHUP
        else:
            opponent_team = db.execute(
                select(Team).where(
                    Team.league_id == league.id, Team.yahoo_team_key == opponent_keys[0]
                )
            ).scalar_one_or_none()
            if opponent_team is None:
                opponent_reason = OPPONENT_REASON_TEAM_NOT_SYNCED

    return target_week, week_range, opponent_team, opponent_reason


def _resolve_stream_window(week_range, resolved_as_of: date) -> tuple[date, date, str]:
    """Clamp INTO the week both directions (mirrors matchup's window-basis
    rule -- see league_matchup's own comment for the demo-blocking bug this
    guards against): a live week clamps forward to today ("remaining"), a
    week entirely in the past or future clamps to the WHOLE week rather than
    an empty/invalid window ("full_week"). Shared by /matchup and /adds.
    """
    if week_range.start_date <= resolved_as_of <= week_range.end_date:
        return resolved_as_of, week_range.end_date, STREAM_WINDOW_REMAINING
    return week_range.start_date, week_range.end_date, STREAM_WINDOW_FULL_WEEK


@router.get("/api/leagues/{league_id}/matchup")
def league_matchup(
    league_id: int,
    week: int | None = None,
    as_of: date | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
    client: YahooClient = Depends(get_yahoo_client),
    advisor: AdvisorClient | None = Depends(get_advisor_client),
) -> dict:
    league = _get_owned_league(db, user, league_id)

    if week is not None and week < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="week must be >= 1")

    # _get_owned_league already proved a Team row with this user_id exists in
    # this league; re-select it here for its id/roster/yahoo_team_key
    my_team = db.execute(
        select(Team).where(Team.league_id == league.id, Team.user_id == user.id)
    ).scalar_one_or_none()
    if my_team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # one scoreboard call answers two questions: which week (week=None means
    # "whatever week is current" to Yahoo, mirroring /overview) and who the
    # opponent is (the other team_key in my_team's matchup for that week) --
    # shared with /adds via _resolve_week_and_opponent
    target_week, week_range, opponent_team, opponent_reason = _resolve_week_and_opponent(
        db, client, league, my_team, week
    )

    season = get_settings().current_season
    resolved_source = _resolve_projection_source(db, season, None)
    rows = _draftable_rows(db, season, resolved_source)
    zscores = _zscores_for(rows)
    abbr_to_nba_id, internal_id_to_nba_id = _nba_team_id_maps(db)

    mine_side = _team_side(
        db,
        my_team,
        rows,
        zscores,
        abbr_to_nba_id,
        internal_id_to_nba_id,
        week_range.start_date,
        week_range.end_date,
    )
    opponent_side = (
        _team_side(
            db,
            opponent_team,
            rows,
            zscores,
            abbr_to_nba_id,
            internal_id_to_nba_id,
            week_range.start_date,
            week_range.end_date,
        )
        if opponent_team is not None
        else None
    )

    mine_games: float = mine_side["projection"].games
    opponent_games: float | None = opponent_side["projection"].games if opponent_side else None
    # the missing-schedule guard: zero games for a roster means every
    # projected total is 0.0, which reads as a real 0-0 tie unless flagged --
    # exactly what an unsynced/stale schedule looks like (see matchup.py's own
    # 0-0-excluded-from-close comment for the same failure mode)
    schedule_ok = mine_games > 0 and (opponent_side is None or (opponent_games or 0) > 0)

    # as_of defaults to the real wall clock -- the sensible default for "what
    # days are left to stream" in live use. Callers viewing a specific week
    # explicitly pass ?as_of= (documented in frontend/lib/api.ts).
    resolved_as_of = as_of if as_of is not None else date.today()

    comparison_out = None
    streaming_out = None
    if opponent_side is not None:
        comparison = compare_matchup(mine_side["projection"], opponent_side["projection"])
        comparison_out = {
            "categories": [
                {
                    "category": cv.category,
                    "mine": _round2(cv.mine),
                    "theirs": _round2(cv.theirs),
                    "margin": _round2(cv.margin),
                    "verdict": cv.verdict,
                }
                for cv in comparison.categories
            ],
            "projected_score": list(comparison.projected_score),
            "close_categories": list(comparison.close_categories),
            "focus": list(comparison.focus),
        }

        # streaming window: the remaining days of a LIVE week (as_of falls
        # inside [week_start, week_end]) clamps forward to today, same as
        # before. But as_of falling OUTSIDE that range -- a week that's
        # already over (the common demo-data shape: a fixed seeded week and a
        # moving wall clock) or one that hasn't started -- clamps to the
        # WHOLE week rather than producing an empty/invalid window. Returning
        # nothing here would teach the user the optimizer is broken; the
        # honest middle ground is "here's the full week's plan," flagged via
        # window_basis so the UI never implies these are adds still
        # actionable today. Shared with /adds via _resolve_stream_window.
        stream_start, stream_end, window_basis = _resolve_stream_window(week_range, resolved_as_of)
        league_rostered = _league_rostered_player_ids(db, league)
        candidates = _streaming_candidates(
            db, rows, league_rostered, internal_id_to_nba_id, stream_start, stream_end
        )
        plan = plan_streaming(
            candidates,
            frozenset(comparison.close_categories),
            stream_start,
            stream_end,
            _league_max_weekly_adds(league),
            # this endpoint's contract has no ?punt= today -- explicit empty
            # set rather than relying on plan_streaming's default, so a
            # future punt-aware caller can't silently inherit a stale
            # assumption about what "no punt passed" meant here
            punt=frozenset(),
        )
        streaming_out = {
            "slots": [
                {
                    "day": slot.day.isoformat(),
                    "player_key": slot.player_key,
                    # slot.player_key is str(nba_player_id) (see
                    # _streaming_candidates) -- rows is already loaded for
                    # this request, so this is a dict lookup, not a new query;
                    # same display fields the draft board/adds endpoint emit
                    # so the page can render one avatar-plus-name treatment
                    "name": rows[int(slot.player_key)].nba_player.full_name,
                    "position": rows[int(slot.player_key)].nba_player.position,
                    "nba_person_id": rows[int(slot.player_key)].nba_player.nba_person_id,
                    "headshot_url": _HEADSHOT_URL_TEMPLATE.format(
                        nba_person_id=rows[int(slot.player_key)].nba_player.nba_person_id
                    ),
                    "games_added": slot.games_added,
                    "categories_helped": list(slot.categories_helped),
                    "reason": list(slot.reason),
                }
                for slot in plan.slots
            ],
            "adds_used": plan.adds_used,
            "adds_reserved": plan.adds_reserved,
            "notes": list(plan.notes),
            "window_basis": window_basis,
        }

    outcome = explain(
        db,
        _matchup_advisor_request(streaming_out, comparison_out, target_week),
        client=advisor,
        model=get_settings().anthropic_model,
    )

    stale, synced_at = _league_stale_and_synced_at(league)
    return {
        "week": target_week,
        "week_range": {
            "start_date": week_range.start_date.isoformat(),
            "end_date": week_range.end_date.isoformat(),
            "is_derived": week_range.is_derived,
        },
        "as_of": resolved_as_of.isoformat(),
        "mine": _side_out(mine_side),
        "opponent": _side_out(opponent_side) if opponent_side is not None else None,
        "opponent_reason": opponent_reason,
        "comparison": comparison_out,
        **_explanations_out(outcome),
        "schedule_coverage": {
            "mine_games": _round2(mine_games),
            "opponent_games": _round2(opponent_games) if opponent_games is not None else None,
            "ok": schedule_ok,
        },
        "streaming": streaming_out,
        "stale": stale,
        "synced_at": synced_at,
    }


def _matchup_advisor_request(
    streaming_out: dict | None, comparison_out: dict | None, week: int
) -> AdvisorRequest:
    """Shape the week's streaming plan for the advisor.

    The shortlist is one entry per PLANNED ADD (a player on a day), not per
    player: the same player can legitimately appear on two days, and each is a
    separate decision, so the item key carries the day too.

    A4 note specific to this feature: the opponent is another real person.
    Their team name never goes in the prompt -- only the category margins,
    which are arithmetic. The engine's own comparison is the context; who they
    are is not.
    """
    if streaming_out is None:
        # no opponent means no close categories means no plan; there is nothing
        # to rank, and the page already explains why
        return AdvisorRequest(feature=FEATURE_MATCHUP, situation=f"week {week}")

    shortlist = tuple(
        ShortlistItem(
            # day-qualified: two slots for the same player on different days
            # are two different decisions and must not collide
            item_key=f"{slot['day']}:{slot['player_key']}",
            label=slot["name"],
            detail=f"add on {slot['day']}",
            metrics={"games_added": slot["games_added"]},
            tags=_matchup_slot_tags(slot),
        )
        for slot in streaming_out["slots"][:MATCHUP_ADVISOR_SHORTLIST_MAX]
    )

    context: dict[str, str] = {
        "adds used by this plan": str(streaming_out["adds_used"]),
        "adds held back": str(streaming_out["adds_reserved"]),
    }
    if comparison_out is not None:
        mine, theirs = comparison_out["projected_score"]
        context["projected category score"] = f"{mine}-{theirs}"
        context["close categories"] = (
            ", ".join(comparison_out["close_categories"]) or "none this week"
        )
        context["most flippable first"] = ", ".join(comparison_out["focus"]) or "none"

    return AdvisorRequest(
        feature=FEATURE_MATCHUP,
        situation=f"streaming adds for week {week}",
        context=context,
        shortlist=shortlist,
    )


def _matchup_slot_tags(slot: dict) -> tuple[str, ...]:
    # same reason as _adds_tags: the engine's reason field is contract keys,
    # which mean nothing to a model reading them cold
    tags: list[str] = []
    if slot["categories_helped"]:
        tags.append(f"helps {', '.join(slot['categories_helped'])}")
    if "back_to_back" in slot["reason"]:
        tags.append("back-to-back, so two games from one add")
    return tuple(tags)


# --- GET /api/leagues/{league_id}/adds ---


@router.get("/api/leagues/{league_id}/adds")
def league_adds(
    league_id: int,
    week: int | None = None,
    as_of: date | None = None,
    punt: list[str] = Query(default=[]),
    limit: int = 25,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
    client: YahooClient = Depends(get_yahoo_client),
    advisor: AdvisorClient | None = Depends(get_advisor_client),
) -> dict:
    league = _get_owned_league(db, user, league_id)

    if week is not None and week < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="week must be >= 1")
    if not (1 <= limit <= 50):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="limit must be between 1 and 50"
        )
    _validate_punt_categories(punt)

    my_team = db.execute(
        select(Team).where(Team.league_id == league.id, Team.user_id == user.id)
    ).scalar_one_or_none()
    if my_team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # same week/opponent resolution the matchup endpoint uses -- see
    # _resolve_week_and_opponent's docstring
    target_week, week_range, opponent_team, opponent_reason = _resolve_week_and_opponent(
        db, client, league, my_team, week
    )

    season = get_settings().current_season
    resolved_source = _resolve_projection_source(db, season, None)
    rows = _draftable_rows(db, season, resolved_source)
    zscores = _zscores_for(rows)
    abbr_to_nba_id, internal_id_to_nba_id = _nba_team_id_maps(db)

    mine_side = _team_side(
        db, my_team, rows, zscores, abbr_to_nba_id, internal_id_to_nba_id,
        week_range.start_date, week_range.end_date,
    )  # fmt: skip
    mine_games: float = mine_side["projection"].games
    roster_zscores = mine_side["roster_zscores"]

    # close_categories drives which categories score_waiver_candidates
    # weights on top of roster need -- degrades to an empty set (need-only
    # ranking) when no opponent can be identified, per the plan; the WHY is
    # surfaced via opponent_reason (same token vocabulary as /matchup) so the
    # page can say it's ranking on need alone rather than this week's matchup
    close_categories: frozenset[str] = frozenset()
    opponent_games: float | None = None
    if opponent_team is not None:
        opponent_side = _team_side(
            db, opponent_team, rows, zscores, abbr_to_nba_id, internal_id_to_nba_id,
            week_range.start_date, week_range.end_date,
        )  # fmt: skip
        opponent_games = opponent_side["projection"].games
        comparison = compare_matchup(mine_side["projection"], opponent_side["projection"])
        close_categories = frozenset(comparison.close_categories)

    # same missing-schedule guard as /matchup -- see its comment
    schedule_ok = mine_games > 0 and (opponent_team is None or (opponent_games or 0) > 0)

    resolved_as_of = as_of if as_of is not None else date.today()
    stream_start, stream_end, window_basis = _resolve_stream_window(week_range, resolved_as_of)

    league_rostered = _league_rostered_player_ids(db, league)
    candidates = _waiver_candidates(
        db, rows, league_rostered, internal_id_to_nba_id, stream_start, stream_end
    )
    scores = score_waiver_candidates(
        candidates, close_categories, roster_zscores, punt=frozenset(punt), limit=limit
    )

    candidates_out = []
    for s in scores:
        pid = int(s.player_key)
        row = rows[pid]
        candidates_out.append(
            {
                "player_key": s.player_key,
                "name": row.nba_player.full_name,
                "position": row.nba_player.position,
                # matches the draft board's fields so the page renders
                # avatars the same way for both lists
                "nba_person_id": row.nba_player.nba_person_id,
                "headshot_url": _HEADSHOT_URL_TEMPLATE.format(
                    nba_person_id=row.nba_player.nba_person_id
                ),
                "score": _round2(s.score),
                "games_remaining": _round2(s.games_remaining),
                "categories_helped": list(s.categories_helped),
                "stat_basis": s.stat_basis,
                "reasons": list(s.reasons),
            }
        )

    outcome = explain(
        db,
        _adds_advisor_request(
            candidates_out, target_week, window_basis, close_categories, opponent_reason, punt
        ),
        client=advisor,
        model=get_settings().anthropic_model,
    )

    stale, synced_at = _league_stale_and_synced_at(league)
    return {
        "week": target_week,
        "week_range": {
            "start_date": week_range.start_date.isoformat(),
            "end_date": week_range.end_date.isoformat(),
            "is_derived": week_range.is_derived,
        },
        "as_of": resolved_as_of.isoformat(),
        "window_basis": window_basis,
        "close_categories": list(close_categories),
        "opponent_reason": opponent_reason,
        "candidates": candidates_out,
        **_explanations_out(outcome),
        "schedule_coverage": {
            "mine_games": _round2(mine_games),
            "opponent_games": _round2(opponent_games) if opponent_games is not None else None,
            "ok": schedule_ok,
        },
        "stale": stale,
        "synced_at": synced_at,
    }


def _adds_advisor_request(
    candidates: list[dict],
    week: int,
    window_basis: str,
    close_categories: list[str],
    opponent_reason: str | None,
    punt: list[str],
) -> AdvisorRequest:
    """Shape the waiver shortlist for the advisor.

    Same A4 rule as the draft builder: player names, stat-derived numbers and
    the engine's own reasons only. Nothing user-scoped, and in particular no
    team or league name -- a league is other people, and their team names are
    theirs.
    """
    shortlist = tuple(
        ShortlistItem(
            item_key=c["player_key"],
            label=c["name"],
            detail=c["position"],
            metrics={"score": c["score"], "games_remaining": c["games_remaining"]},
            tags=_adds_tags(c),
        )
        for c in candidates[:ADDS_ADVISOR_SHORTLIST_MAX]
    )
    window = (
        "the rest of this week" if window_basis == STREAM_WINDOW_REMAINING else "the full week"
    )
    return AdvisorRequest(
        feature=FEATURE_ADDS,
        situation=f"free-agent adds for week {week}, covering {window}",
        context={
            "ranking targets": (
                ", ".join(close_categories)
                if close_categories
                else "roster need alone (no close categories this week)"
            ),
            # the honesty surface the Adds page already shows: say when the
            # ranking degraded to need-only so the model doesn't reason as if
            # it were matchup-weighted
            "matchup basis": (
                "no opponent identified, so this is roster need only"
                if opponent_reason
                else "weighted toward this week's matchup"
            ),
            "punting": ", ".join(c for c in CATEGORIES if c in set(punt)) or "nothing",
        },
        shortlist=shortlist,
    )


def _adds_tags(candidate: dict) -> tuple[str, ...]:
    """Render an AddsCandidate's structured tokens into prompt-readable text.

    The engine emits contract keys ("schedule_driven"), which are meaningless
    to a model reading them cold. This is the only place the backend turns them
    into words, and it stays deliberately terse -- the frontend's own
    translation (components/dashboard/adds/tokens.ts) is the user-facing copy
    and the two are allowed to differ.
    """
    tags: list[str] = []
    if candidate["categories_helped"]:
        tags.append(f"helps {', '.join(candidate['categories_helped'])}")
    if "schedule_driven" in candidate["reasons"]:
        tags.append("plays more games than most of this pool")
    if candidate["stat_basis"] == "season_average":
        tags.append("valued off last season's averages, not a projection")
    return tuple(tags)


# --- GET /api/leagues/{league_id}/trades ---

# value_basis token -- discloses the T3 plan amendment (docs/trade-analyzer-
# plan.md): net_value/verdict weigh CATEGORY IMPACT only, never positional
# scarcity, because evaluate_trades's inputs (two RosterPlayer lists) carry
# no position data at all. Structured, not English, per the same discipline
# every other reason field in this module follows.
TRADE_VALUE_BASIS_CATEGORY_IMPACT_ONLY = "category_impact_only"


def _strength_out(strength) -> dict:
    return {
        "category": strength.category,
        "total": _round2(strength.total),
        "mean": _round2(strength.mean),
        "label": strength.label,
        "depth": strength.depth,
        "fragile": strength.fragile,
        "top_contributor": strength.top_contributor,
        "top_share": _round2(strength.top_share),
    }


def _side_outcome_out(outcome, roster_size: int) -> dict:
    # roster_size is constant pre/post for a given side -- generate_trade_
    # candidates only ever swaps equal-length give/get packages -- so one
    # size safely derives both before and after means
    def _profile_out(profile: dict) -> dict:
        return {
            "totals": {cat: _round2(profile["totals"][cat]) for cat in CATEGORIES},
            "labels": profile["labels"],
            "means": {
                cat: _round2((profile["totals"][cat] / roster_size) if roster_size else 0.0)
                for cat in CATEGORIES
            },
        }

    return {
        "before": _profile_out(outcome.before),
        "after": _profile_out(outcome.after),
        "gained": list(outcome.gained),
        "lost": list(outcome.lost),
        "collapsed": list(outcome.collapsed),
    }


@router.get("/api/leagues/{league_id}/trades")
def league_trades(
    league_id: int,
    team_id: int,
    max_package: int = 2,
    limit: int = 10,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
    advisor: AdvisorClient | None = Depends(get_advisor_client),
) -> dict:
    league = _get_owned_league(db, user, league_id)

    my_team = db.execute(
        select(Team).where(Team.league_id == league.id, Team.user_id == user.id)
    ).scalar_one_or_none()
    if my_team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    if team_id == my_team.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="team_id must be a different team than your own",
        )
    # scoped to Team.league_id == league.id -- a team_id that exists but
    # belongs to a DIFFERENT league must 404, never be compared, or one
    # user's trade query could leak another league's roster data
    other_team = db.execute(
        select(Team).where(Team.id == team_id, Team.league_id == league.id)
    ).scalar_one_or_none()
    if other_team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="team_id not found in this league"
        )

    if not (1 <= max_package <= 2):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="max_package must be between 1 and 2"
        )
    if not (1 <= limit <= 25):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="limit must be between 1 and 25"
        )

    season = get_settings().current_season
    resolved_source = _resolve_projection_source(db, season, None)
    rows = _draftable_rows(db, season, resolved_source)
    # one shared z population for BOTH rosters, per the task brief -- two
    # independently-scaled rosters would not be comparable on the same axis
    zscores = _zscores_for(rows)

    mine_players, mine_info = _roster_players(db, my_team, rows, zscores)
    theirs_players, theirs_info = _roster_players(db, other_team, rows, zscores)
    players_out = {**mine_info, **theirs_info}

    comparison = compare_rosters(mine_players, theirs_players)
    candidate_set = generate_trade_candidates(
        mine_players, theirs_players, comparison=comparison, max_package=max_package
    )
    verdicts = evaluate_trades(
        list(candidate_set.candidates),
        mine_players,
        theirs_players,
        config=_league_config(league),
        limit=limit,
    )

    verdicts_out = [
        {
            "give": list(v.candidate.give),
            "get": list(v.candidate.get),
            "mine": _side_outcome_out(v.mine, len(mine_players)),
            "theirs": _side_outcome_out(v.theirs, len(theirs_players)),
            "net_value": _round2(v.net_value),
            "verdict": v.verdict,
            "reasons": list(v.reasons),
        }
        for v in verdicts
    ]

    outcome = explain(
        db,
        _trades_advisor_request(verdicts_out, players_out, comparison),
        client=advisor,
        model=get_settings().anthropic_model,
    )

    stale, synced_at = _league_stale_and_synced_at(league)
    return {
        "mine": {
            "team_id": my_team.id,
            "categories": {cat: _strength_out(comparison.mine[cat]) for cat in CATEGORIES},
            "surplus": list(comparison.my_surplus),
            "deficit": list(comparison.my_deficit),
        },
        "theirs": {
            "team_id": other_team.id,
            "categories": {cat: _strength_out(comparison.theirs[cat]) for cat in CATEGORIES},
            "surplus": list(comparison.their_surplus),
            "deficit": list(comparison.their_deficit),
        },
        "players": players_out,
        "verdicts": verdicts_out,
        **_explanations_out(outcome),
        "evaluated": candidate_set.evaluated,
        "truncated": candidate_set.truncated,
        "value_basis": TRADE_VALUE_BASIS_CATEGORY_IMPACT_ONLY,
        "stale": stale,
        "synced_at": synced_at,
    }


def _trades_advisor_request(
    verdicts: list[dict], players: dict[str, dict], comparison
) -> AdvisorRequest:
    """Shape trade proposals for the advisor.

    This is the feature that forced the shortlist to be items rather than
    players: a proposal is a give/get PAIR, so there is no single player to
    name and no player key to echo back.

    The item key is the proposal's position in the engine's own ranking, not a
    player key. That keeps it short, stable for the cache, and free of ids --
    the label carries the names, which is what the model actually reasons over.

    A4 note: the other team belongs to another real person. Their team name is
    never sent; the proposals and the category strengths are, because those are
    arithmetic over public player stats.
    """
    shortlist = tuple(
        ShortlistItem(
            item_key=f"proposal-{i}",
            label=(
                f"give {_trade_names(v['give'], players)}"
                f" / get {_trade_names(v['get'], players)}"
            ),
            detail=f"engine verdict: {v['verdict']}",
            metrics={"net_value": v["net_value"]},
            tags=_trade_tags(v),
        )
        for i, v in enumerate(verdicts[:TRADES_ADVISOR_SHORTLIST_MAX])
    )
    return AdvisorRequest(
        feature=FEATURE_TRADES,
        situation="trade proposals with one other team in a 9-cat league",
        context={
            "my surplus": ", ".join(comparison.my_surplus) or "none",
            "my deficit": ", ".join(comparison.my_deficit) or "none",
            "their surplus": ", ".join(comparison.their_surplus) or "none",
            "their deficit": ", ".join(comparison.their_deficit) or "none",
            # the same caveat the page shows: net_value weighs category impact
            # only, so the model must not present it as an all-in valuation
            "how net_value was computed": (
                "category impact only -- it ignores positional scarcity entirely"
            ),
        },
        shortlist=shortlist,
    )


def _trade_names(player_keys: list[str], players: dict[str, dict]) -> str:
    # players is the display map the response already carries, so a proposal
    # never renders to the model as a list of raw keys
    return ", ".join(players[k]["name"] for k in player_keys if k in players) or "nobody"


def _trade_tags(verdict: dict) -> tuple[str, ...]:
    tags: list[str] = []
    if verdict["mine"]["gained"]:
        tags.append(f"I gain {', '.join(verdict['mine']['gained'])}")
    if verdict["mine"]["lost"]:
        tags.append(f"I lose {', '.join(verdict['mine']['lost'])}")
    # a collapsed category is the one that should stop a trade outright: it
    # means the category doesn't just weaken, it stops existing
    if verdict["mine"]["collapsed"]:
        tags.append(f"I collapse {', '.join(verdict['mine']['collapsed'])} entirely")
    return tuple(tags)
