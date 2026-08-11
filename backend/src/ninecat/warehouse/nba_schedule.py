"""Sync the NBA schedule into the warehouse and answer games-per-date-range questions.

Every later fantasy-week module (games-per-week, streaming targets, etc.) is built
on top of `games_in_range` / `back_to_backs_in_range`, so those two stay small and
exact rather than folding in any fantasy-specific logic.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.models.warehouse import NbaGame, NbaTeam

# a normalized schedule row, shaped the same whether it came from nba_api or a
# test fixture: {game_id, game_date, home_team_id, home_team_name,
# home_team_abbreviation, away_team_id, away_team_name, away_team_abbreviation}
ScheduleRow = Mapping[str, object]
Fetcher = Callable[[str], Iterable[ScheduleRow]]


class GamesInRange(NamedTuple):
    """Result of games_in_range: how many games, and on which dates."""

    count: int
    dates: list[date]


def _default_fetcher(season: str) -> list[ScheduleRow]:
    """Pull a season's schedule from nba_api's ScheduleLeagueV2 endpoint.

    Imported lazily so importing this module (or running the test suite, which
    always injects a fetcher) never requires nba_api or network access.
    """
    from nba_api.stats.endpoints import scheduleleaguev2

    response = scheduleleaguev2.ScheduleLeagueV2(season=season)
    payload = response.season_games.get_dict()
    headers: list[str] = payload["headers"]

    def col(row: list, name: str) -> object:
        return row[headers.index(name)]

    normalized: list[ScheduleRow] = []
    for row in payload["data"]:
        # gameDateEst is the schedule date NBA.com actually publishes games under;
        # only the first 10 chars ("YYYY-MM-DD") are kept, the rest is a time-of-day
        game_date_raw = str(col(row, "gameDateEst"))[:10]
        normalized.append(
            {
                "game_id": str(col(row, "gameId")),
                "game_date": game_date_raw,
                "home_team_id": int(col(row, "homeTeam_teamId")),
                "home_team_name": (
                    f"{col(row, 'homeTeam_teamCity')} {col(row, 'homeTeam_teamName')}"
                ).strip(),
                "home_team_abbreviation": col(row, "homeTeam_teamTricode"),
                "away_team_id": int(col(row, "awayTeam_teamId")),
                "away_team_name": (
                    f"{col(row, 'awayTeam_teamCity')} {col(row, 'awayTeam_teamName')}"
                ).strip(),
                "away_team_abbreviation": col(row, "awayTeam_teamTricode"),
            }
        )
    return normalized


def _parse_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def sync_schedule(session: Session, season: str, fetcher: Fetcher | None = None) -> int:
    """Fetch a season's schedule and upsert NbaTeam/NbaGame rows idempotently.

    `fetcher` defaults to a live nba_api call; tests inject a fixture-backed
    callable instead so the suite never hits the network. Returns the number of
    game rows upserted.
    """
    fetch = fetcher or _default_fetcher
    rows = list(fetch(season))
    if not rows:
        return 0

    # teams must exist (with their internal bigint ids) before games can FK onto
    # them; collect the distinct set from both sides of every row first
    teams_by_nba_id: dict[int, dict[str, object]] = {}
    for row in rows:
        teams_by_nba_id[int(row["home_team_id"])] = {
            "name": row["home_team_name"],
            "abbreviation": row["home_team_abbreviation"],
        }
        teams_by_nba_id[int(row["away_team_id"])] = {
            "name": row["away_team_name"],
            "abbreviation": row["away_team_abbreviation"],
        }

    # ON CONFLICT DO UPDATE keyed on nba_team_id: re-running a sync (or two
    # seasons sharing a team) updates the name/abbreviation instead of duplicating
    team_insert = pg_insert(NbaTeam).values(
        [
            {"nba_team_id": nba_team_id, "name": info["name"], "abbreviation": info["abbreviation"]}
            for nba_team_id, info in teams_by_nba_id.items()
        ]
    )
    team_stmt = team_insert.on_conflict_do_update(
        index_elements=[NbaTeam.nba_team_id],
        set_={
            "name": team_insert.excluded.name,
            "abbreviation": team_insert.excluded.abbreviation,
        },
    ).returning(NbaTeam.id, NbaTeam.nba_team_id)
    team_internal_id_by_nba_id = {
        nba_team_id: internal_id for internal_id, nba_team_id in session.execute(team_stmt)
    }

    game_values = [
        {
            "nba_game_id": str(row["game_id"]),
            "game_date": _parse_date(row["game_date"]),
            "season": season,
            "home_team_id": team_internal_id_by_nba_id[int(row["home_team_id"])],
            "away_team_id": team_internal_id_by_nba_id[int(row["away_team_id"])],
        }
        for row in rows
    ]
    game_insert = pg_insert(NbaGame).values(game_values)
    game_stmt = game_insert.on_conflict_do_update(
        # nba_game_id is NBA.com's own id: the natural idempotency key for a game
        index_elements=[NbaGame.nba_game_id],
        set_={
            "game_date": game_insert.excluded.game_date,
            "season": game_insert.excluded.season,
            "home_team_id": game_insert.excluded.home_team_id,
            "away_team_id": game_insert.excluded.away_team_id,
            # onupdate=func.now() on the column does NOT fire for ON CONFLICT
            # updates (SQLAlchemy only applies onupdate to ORM-driven UPDATEs),
            # so it must be set explicitly here or synced_at would freeze at
            # first-insert time on every later resync
            "synced_at": func.now(),
        },
    )
    session.execute(game_stmt)

    return len(game_values)


def games_in_range(
    session: Session, nba_team_id: int, start_date: date, end_date: date
) -> GamesInRange:
    """Count and list a team's game dates (home or away) within an inclusive range."""
    team = session.execute(
        select(NbaTeam).where(NbaTeam.nba_team_id == nba_team_id)
    ).scalar_one_or_none()
    if team is None:
        return GamesInRange(count=0, dates=[])

    dates = (
        session.execute(
            select(NbaGame.game_date)
            .where(
                NbaGame.game_date >= start_date,
                NbaGame.game_date <= end_date,
                or_(NbaGame.home_team_id == team.id, NbaGame.away_team_id == team.id),
            )
            .order_by(NbaGame.game_date)
        )
        .scalars()
        .all()
    )
    return GamesInRange(count=len(dates), dates=list(dates))


def back_to_backs_in_range(
    session: Session, nba_team_id: int, start_date: date, end_date: date
) -> list[tuple[date, date]]:
    """Find consecutive-day game pairs (back-to-backs) for a team in an inclusive range."""
    dates = games_in_range(session, nba_team_id, start_date, end_date).dates
    return [
        (prev, curr) for prev, curr in zip(dates, dates[1:]) if curr - prev == timedelta(days=1)
    ]
