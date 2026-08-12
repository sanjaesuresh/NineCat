"""Sync league-wide player per-game averages into the warehouse.

Mirrors nba_schedule.sync_schedule's shape: a normalized row format any
fetcher (live nba_api or a test fixture) can produce, and an idempotent
upsert on top of it.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.models.warehouse import NbaPlayer, NbaTeam, PlayerSeasonAverage

# a normalized per-game stat-line row, shaped the same whether it came from
# nba_api or a test fixture: {nba_person_id, full_name, nba_team_id (NBA.com
# team id, or None for a free agent / not-yet-synced team), games_played,
# fgm, fga, ftm, fta, tpm, pts, reb, ast, stl, blk, tov, position (optional --
# nba_api's coarse position string, e.g. "Guard"/"PG"/"F-C"; may be absent,
# blank, or None, all of which are stored as NULL)}
PlayerStatsRow = Mapping[str, Any]
Fetcher = Callable[[str], Iterable[PlayerStatsRow]]

# per-game counting stats the contract requires (makes/attempts, not bare
# percentages) so the engine can compute volume-weighted FG%/FT% z-scores
_STAT_FIELDS = ("fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov")


def _default_fetcher(season: str) -> list[PlayerStatsRow]:
    """Pull league-wide per-game player averages from nba_api's LeagueDashPlayerStats.

    Imported lazily so importing this module (or running the test suite, which
    always injects a fetcher) never requires nba_api or network access.

    LeagueDashPlayerStats' Base measure type doesn't carry a position column
    (unlike CommonAllPlayers/PlayerIndex), so this fetcher never supplies
    "position" -- sync_player_averages' coalesce-on-update means that's safe,
    it just leaves whatever position a prior sync/backfill already stored
    alone. The fixture-injected fetcher used in tests exercises the
    persistence path with real position values.
    """
    from nba_api.stats.endpoints import leaguedashplayerstats

    response = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season, per_mode_detailed="PerGame"
    )
    payload = response.league_dash_player_stats.get_dict()
    headers: list[str] = payload["headers"]

    def col(row: list, name: str) -> object:
        return row[headers.index(name)]

    normalized: list[PlayerStatsRow] = []
    for row in payload["data"]:
        # nba_api reports 0 (not null) for "no current team"; treat both as unset
        team_id = col(row, "TEAM_ID")
        normalized.append(
            {
                "nba_person_id": int(col(row, "PLAYER_ID")),
                "full_name": str(col(row, "PLAYER_NAME")),
                "nba_team_id": int(team_id) if team_id else None,
                "games_played": int(col(row, "GP")),
                "fgm": float(col(row, "FGM")),
                "fga": float(col(row, "FGA")),
                "ftm": float(col(row, "FTM")),
                "fta": float(col(row, "FTA")),
                "tpm": float(col(row, "FG3M")),
                "pts": float(col(row, "PTS")),
                "reb": float(col(row, "REB")),
                "ast": float(col(row, "AST")),
                "stl": float(col(row, "STL")),
                "blk": float(col(row, "BLK")),
                "tov": float(col(row, "TOV")),
            }
        )
    return normalized


def sync_player_averages(session: Session, season: str, fetcher: Fetcher | None = None) -> int:
    """Fetch a season's league-wide per-game averages and upsert NbaPlayer/PlayerSeasonAverage.

    `fetcher` defaults to a live nba_api call; tests inject a fixture-backed
    callable instead so the suite never hits the network. Returns the number
    of PlayerSeasonAverage rows upserted.
    """
    fetch = fetcher or _default_fetcher
    fetched_rows = list(fetch(season))
    if not fetched_rows:
        return 0

    # dedupe by nba_person_id first (last occurrence wins): a fetcher could
    # return the same player twice in one batch (paging overlap, a stale
    # duplicate row, ...), and postgres rejects a multi-row ON CONFLICT DO
    # UPDATE that would affect the same target row twice in one statement --
    # same pattern as sync_schedule's teams_by_nba_id dict
    rows_by_person_id: dict[int, PlayerStatsRow] = {}
    for row in fetched_rows:
        rows_by_person_id[row["nba_person_id"]] = row
    rows = list(rows_by_person_id.values())

    # resolve each row's optional NBA.com team id to our internal NbaTeam id;
    # a team that hasn't been synced yet (or a free agent's None) just leaves
    # the player's team unresolved rather than failing the whole sync --
    # sync_schedule owns creating NbaTeam rows, not this function
    team_nba_ids = {row["nba_team_id"] for row in rows if row.get("nba_team_id")}
    team_internal_id_by_nba_id: dict[int, int] = {}
    if team_nba_ids:
        team_internal_id_by_nba_id = dict(
            session.execute(
                select(NbaTeam.nba_team_id, NbaTeam.id).where(
                    NbaTeam.nba_team_id.in_(team_nba_ids)
                )
            ).all()
        )

    # ON CONFLICT DO UPDATE keyed on nba_person_id: re-running a sync (or a
    # player appearing again in a later sync) updates name/team instead of
    # duplicating the player row
    player_insert = pg_insert(NbaPlayer).values(
        [
            {
                "nba_person_id": row["nba_person_id"],
                "full_name": row["full_name"],
                "nba_team_id": team_internal_id_by_nba_id.get(row.get("nba_team_id")),
                "is_active": True,
                # blank/whitespace-only and missing are all "no position data" --
                # normalize all of them to None rather than storing "" or "  "
                "position": (row.get("position") or "").strip() or None,
            }
            for row in rows
        ]
    )
    player_stmt = player_insert.on_conflict_do_update(
        index_elements=[NbaPlayer.nba_person_id],
        set_={
            "full_name": player_insert.excluded.full_name,
            "nba_team_id": player_insert.excluded.nba_team_id,
            "is_active": player_insert.excluded.is_active,
            # coalesce, not a bare overwrite: the nightly job's live fetcher never
            # supplies a position (see _default_fetcher), so an unconditional
            # excluded.position would NULL out every player's position on every
            # nightly re-sync, wiping any future backfill. A row that DOES carry
            # a position (fixture/backfill) still updates it in place.
            "position": func.coalesce(player_insert.excluded.position, NbaPlayer.position),
        },
    ).returning(NbaPlayer.id, NbaPlayer.nba_person_id)
    player_internal_id_by_person_id = {
        person_id: internal_id for internal_id, person_id in session.execute(player_stmt)
    }

    average_values = [
        {
            "nba_player_id": player_internal_id_by_person_id[row["nba_person_id"]],
            "season": season,
            "games_played": row["games_played"],
            **{stat: row[stat] for stat in _STAT_FIELDS},
        }
        for row in rows
    ]
    average_insert = pg_insert(PlayerSeasonAverage).values(average_values)
    average_stmt = average_insert.on_conflict_do_update(
        # (nba_player_id, season) is the natural idempotency key for a season average
        index_elements=[PlayerSeasonAverage.nba_player_id, PlayerSeasonAverage.season],
        set_={
            "games_played": average_insert.excluded.games_played,
            **{stat: getattr(average_insert.excluded, stat) for stat in _STAT_FIELDS},
            # onupdate=func.now() on the column does NOT fire for ON CONFLICT
            # updates (SQLAlchemy only applies onupdate to ORM-driven UPDATEs),
            # so it must be set explicitly here or synced_at would freeze at
            # first-insert time on every later resync
            "synced_at": func.now(),
        },
    )
    session.execute(average_stmt)

    return len(average_values)
