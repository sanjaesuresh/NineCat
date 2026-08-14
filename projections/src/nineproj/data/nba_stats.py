"""Fetch and parse per-season, per-game NBA player stat lines (incl. position).

Every later baseline/projection module builds SeasonLine per-game numbers into
its own math, so this module stays a thin, exact parse of nba_api's raw
resultSets/rowSet shape (headers looked up by name, never positional index)
plus a position enrichment step -- LeagueDashPlayerStats doesn't carry
position, so it's merged in from a second, per-team roster fetch.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_TTL_HOURS = 24  # mirrors schedule.py / settings.cache.ttl_hours default

_STATS_ENDPOINT = "leaguedashplayerstats"
_ROSTER_ENDPOINT = "commonteamroster"
_PROVENANCE_SOURCE = "NBA Stats (stats.nba.com via nba_api)"

# raw nba_api-shaped payload: {"resultSets": [{"name": ..., "headers": [...], "rowSet": [[...], ...]}]}
StatsFetcher = Callable[[str], dict[str, Any]]
RosterFetcher = Callable[[str, int], dict[str, Any]]


@dataclass(frozen=True)
class SeasonLine:
    """One player's per-game stat line for one season, plus makes/attempts.

    Makes/attempts (fgm/fga, ftm/fta) are kept alongside pts/reb/... rather
    than percentages so the engine's volume-weighted FG%/FT% z-score math has
    what it needs (a raw FG_PCT can't be re-weighted by volume after the fact).
    """

    season: str
    player_id: int
    name: str
    team: str
    position: str | None
    age: float
    games: int
    minutes: float
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


# accumulated across every fetch_season_averages call in the process; Task
# 14's exporter reads this via provenance() to build sources.json
_provenance_log: list[dict[str, str]] = []


def provenance() -> list[dict[str, str]]:
    """Every NBA Stats endpoint call made via fetch_season_averages so far."""
    return list(_provenance_log)


def _record_provenance(endpoint: str, season: str) -> None:
    _provenance_log.append(
        {
            "source": _PROVENANCE_SOURCE,
            "endpoint": endpoint,
            "season": season,
            "retrieved": date.today().isoformat(),
        }
    )


def _rows_from_result_set(payload: dict[str, Any], name: str) -> tuple[list[str], list[list[Any]]]:
    """Pull one named resultSet's headers+rowSet out of a raw nba_api-shaped payload."""
    for result_set in payload["resultSets"]:
        if result_set["name"] == name:
            return result_set["headers"], result_set["rowSet"]
    raise KeyError(f"resultSet {name!r} not found in payload")


def _default_stats_fetcher(season: str, cache_dir: Path | None, ttl_hours: float | None) -> dict[str, Any]:
    """Live per-game player averages from nba_api's LeagueDashPlayerStats, through the cache.

    Imported lazily so importing this module never requires nba_api or network
    access; tests always inject a fixture-backed fetcher instead. `ttl_hours`
    is None -> _DEFAULT_CACHE_TTL_HOURS: a last-resort default only, since
    fetch_season_averages' caller (run_projection.py) always threads the real
    settings.cache.ttl_hours through explicitly (H3).
    """
    from nineproj.utils.cache import cached_fetch

    def _fetch_live() -> dict[str, Any]:
        from nba_api.stats.endpoints import leaguedashplayerstats

        response = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season, per_mode_detailed="PerGame"
        )
        return response.nba_response.get_dict()

    return cached_fetch(
        f"leaguedash_{season}",
        ttl_hours if ttl_hours is not None else _DEFAULT_CACHE_TTL_HOURS,
        _fetch_live,
        cache_dir=cache_dir,
        endpoint=_STATS_ENDPOINT,
    )


def _default_roster_fetcher(
    season: str, team_id: int, cache_dir: Path | None, ttl_hours: float | None
) -> dict[str, Any]:
    """Live team roster (for POSITION, absent from LeagueDashPlayerStats), cached per team."""
    from nineproj.utils.cache import cached_fetch

    def _fetch_live() -> dict[str, Any]:
        from nba_api.stats.endpoints import commonteamroster

        response = commonteamroster.CommonTeamRoster(team_id=team_id, season=season)
        return response.nba_response.get_dict()

    return cached_fetch(
        f"roster_{season}_{team_id}",
        ttl_hours if ttl_hours is not None else _DEFAULT_CACHE_TTL_HOURS,
        _fetch_live,
        cache_dir=cache_dir,
        endpoint=_ROSTER_ENDPOINT,
    )


def _positions_by_player_id(
    season: str, team_ids: set[int], roster_fetch: RosterFetcher
) -> dict[int, str]:
    """Map player_id -> POSITION across every team's roster, tolerating a single team's failure.

    Position is optional downstream (slot_classes maps missing/None to
    UTIL-only), so one team's roster fetch failing (stale cache exhausted,
    live call down) shouldn't fail the whole universe build -- it just leaves
    that team's players positionless.
    """
    positions: dict[int, str] = {}
    for team_id in team_ids:
        try:
            payload = roster_fetch(season, team_id)
        except Exception:
            logger.warning(
                "roster fetch failed for team_id=%s season=%s; positions left null", team_id, season
            )
            continue
        headers, rows = _rows_from_result_set(payload, "CommonTeamRoster")
        player_id_idx = headers.index("PLAYER_ID")
        position_idx = headers.index("POSITION")
        for row in rows:
            position = row[position_idx]
            if position:
                positions[int(row[player_id_idx])] = str(position)
    return positions


def fetch_season_averages(
    season: str,
    fetcher: StatsFetcher | None = None,
    roster_fetcher: RosterFetcher | None = None,
    cache_dir: Path | None = None,
    ttl_hours: float | None = None,
) -> list[SeasonLine]:
    """Fetch and parse one season's per-game player averages, enriched with position.

    `fetcher`/`roster_fetcher` default to live nba_api calls (through the
    on-disk cache); tests always inject fixture-backed callables instead, so
    the suite never touches the network. Header lookups only (never positional
    indices) so a column-order change in nba_api's response can't silently
    corrupt a stat. `ttl_hours` only matters for the default (live) fetchers --
    an injected fetcher/roster_fetcher ignores it entirely.
    """
    fetch = fetcher or (lambda s: _default_stats_fetcher(s, cache_dir, ttl_hours))
    roster_fetch = roster_fetcher or (lambda s, t: _default_roster_fetcher(s, t, cache_dir, ttl_hours))

    payload = fetch(season)
    _record_provenance(_STATS_ENDPOINT, season)
    headers, rows = _rows_from_result_set(payload, "LeagueDashPlayerStats")

    def col(row: list[Any], name: str) -> Any:
        return row[headers.index(name)]

    # nba_api reports 0 (not null) for "no current team"; skip those for roster lookups
    team_ids = {int(col(row, "TEAM_ID")) for row in rows if col(row, "TEAM_ID")}
    positions = _positions_by_player_id(season, team_ids, roster_fetch) if team_ids else {}

    lines: list[SeasonLine] = []
    for row in rows:
        player_id = int(col(row, "PLAYER_ID"))
        lines.append(
            SeasonLine(
                season=season,
                player_id=player_id,
                name=str(col(row, "PLAYER_NAME")),
                team=str(col(row, "TEAM_ABBREVIATION")),
                position=positions.get(player_id),
                age=float(col(row, "AGE")),
                games=int(col(row, "GP")),
                minutes=float(col(row, "MIN")),
                fgm=float(col(row, "FGM")),
                fga=float(col(row, "FGA")),
                ftm=float(col(row, "FTM")),
                fta=float(col(row, "FTA")),
                tpm=float(col(row, "FG3M")),
                pts=float(col(row, "PTS")),
                reb=float(col(row, "REB")),
                ast=float(col(row, "AST")),
                stl=float(col(row, "STL")),
                blk=float(col(row, "BLK")),
                tov=float(col(row, "TOV")),
            )
        )
    return lines
