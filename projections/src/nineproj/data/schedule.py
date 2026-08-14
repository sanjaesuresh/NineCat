"""Fetch the NBA schedule and answer fantasy-week / playoff-window questions.

`playoff_profile` includes a 0-1 `playoff_schedule_score`, min-max normalized
against every team in the same `Schedule` (see `_normalize_playoff_score`).
`league_playoff_game_counts` stays public alongside it — Task 11's composite
scoring consumes the raw per-team totals directly rather than re-deriving them
from N calls to `playoff_profile`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import NamedTuple

from nineproj.config import Settings

# a normalized schedule row, shaped the same whether it came from nba_api or a
# test fixture: one game, its date, and the two teams' abbreviations
class ScheduleRow(NamedTuple):
    game_date: str  # ISO "YYYY-MM-DD"
    home_team_abbr: str
    away_team_abbr: str


Fetcher = Callable[[str], Iterable[ScheduleRow]]


@dataclass(frozen=True)
class Schedule:
    """Per-team sorted game-date lists, normalized from any fetcher's raw rows."""

    team_game_dates: dict[str, list[date]]


@dataclass(frozen=True)
class ScheduleUnavailable:
    """Sentinel returned instead of a Schedule when the season's games can't be
    fetched (D6): the fetcher raised, or returned no games. A frozen dataclass
    (not a bare exception) so every consumer can isinstance-check it and hand
    back its own typed all-None result instead of raising or fabricating data.
    """


@dataclass(frozen=True)
class PlayoffProfile:
    """A team's game load inside the configured playoff window (default weeks 19-21)."""

    games_by_week: dict[int, int]
    playoff_games: int
    playoff_b2b_count: int
    # min-max normalized against every team in the same schedule (0 = fewest
    # playoff-window games in the league, 1 = most); None only when unavailable
    playoff_schedule_score: float | None


@dataclass(frozen=True)
class UnavailableProfile:
    """Same field names as PlayoffProfile, all None — the D6 unavailable result."""

    games_by_week: None = None
    playoff_games: None = None
    playoff_b2b_count: None = None
    playoff_schedule_score: None = None


_DEFAULT_CACHE_TTL_HOURS = 24  # mirrors config/settings.json's cache.ttl_hours default


def _default_fetcher(season: str, ttl_hours: float | None = None) -> list[ScheduleRow]:
    """Pull a season's schedule from nba_api's ScheduleLeagueV2 endpoint, through the cache.

    Imported lazily (both nba_api and the cache helper) so importing this module
    never requires nba_api, httpx, or network access; tests always inject a
    fixture-backed fetcher instead and never exercise this function. `ttl_hours`
    is None -> _DEFAULT_CACHE_TTL_HOURS: a last-resort default, since the real
    caller threads settings.cache.ttl_hours through explicitly (H3).
    """
    from nineproj.utils.cache import cached_fetch

    def _fetch_live() -> list[list[str]]:
        from nba_api.stats.endpoints import scheduleleaguev2

        response = scheduleleaguev2.ScheduleLeagueV2(season=season)
        payload = response.season_games.get_dict()
        headers: list[str] = payload["headers"]

        def col(row: list, name: str) -> object:
            return row[headers.index(name)]

        # plain lists (not ScheduleRow tuples) so this is JSON-serializable for
        # the on-disk cache; rehydrated into ScheduleRow after cached_fetch returns
        return [
            [
                str(col(row, "gameDateEst"))[:10],
                str(col(row, "homeTeam_teamTricode")),
                str(col(row, "awayTeam_teamTricode")),
            ]
            for row in payload["data"]
        ]

    raw_rows = cached_fetch(
        f"schedule_{season}",
        ttl_hours if ttl_hours is not None else _DEFAULT_CACHE_TTL_HOURS,
        _fetch_live,
    )
    return [ScheduleRow(*row) for row in raw_rows]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def fetch_schedule(
    season: str, fetcher: Fetcher | None = None, ttl_hours: float | None = None
) -> Schedule | ScheduleUnavailable:
    """Fetch and normalize a season's schedule into per-team sorted game-date lists.

    Never raises (D6): a fetcher error or an empty game list both collapse to
    `ScheduleUnavailable` so downstream code can branch on it explicitly.
    `ttl_hours` only matters for the default (live) fetcher.
    """
    fetch = fetcher or (lambda s: _default_fetcher(s, ttl_hours))
    try:
        rows = list(fetch(season))
    except Exception:
        return ScheduleUnavailable()

    if not rows:
        return ScheduleUnavailable()

    team_dates: dict[str, list[date]] = defaultdict(list)
    for row in rows:
        game_date = _parse_date(row.game_date)
        team_dates[row.home_team_abbr].append(game_date)
        team_dates[row.away_team_abbr].append(game_date)

    return Schedule(team_game_dates={team: sorted(dates) for team, dates in team_dates.items()})


def fantasy_weeks(settings: Settings) -> dict[int, tuple[date, date]]:
    """Map fantasy week number (1-26) to its (Monday, Sunday) inclusive date range.

    Week 1 starts at settings.fantasy_week1_start (a Monday); every later week
    is exactly 7 days on, matching Yahoo's Mon-Sun matchup cadence for the
    whole regular-season + playoff calendar.
    """
    week1_monday = _parse_date(settings.fantasy_week1_start)
    return {
        week: (
            week1_monday + timedelta(weeks=week - 1),
            week1_monday + timedelta(weeks=week - 1) + timedelta(days=6),
        )
        for week in range(1, 27)
    }


def team_week_games(
    schedule: Schedule | ScheduleUnavailable, weeks: Mapping[int, tuple[date, date]]
) -> dict[str, dict[int, int]]:
    """Count each team's games inside each fantasy week's Mon-Sun range.

    Unavailable schedule -> empty dict: with no teams known there is no
    per-team shape to fill with Nones (PlayoffProfile is where fixed None
    fields apply); an empty mapping is this function's D6 result instead.
    """
    if isinstance(schedule, ScheduleUnavailable):
        return {}

    result: dict[str, dict[int, int]] = {}
    for team, game_dates in schedule.team_game_dates.items():
        result[team] = {
            week_number: sum(1 for d in game_dates if monday <= d <= sunday)
            for week_number, (monday, sunday) in weeks.items()
        }
    return result


def _team_playoff_window(
    team_abbr: str, schedule: Schedule, settings: Settings, window: tuple[int, int] | None = None
) -> tuple[dict[int, int], list[date]]:
    """Shared by playoff_profile and league_playoff_game_counts so neither has to
    call the other (that would recurse: playoff_profile needs the whole league's
    counts for its score, league_playoff_game_counts needs every team's count).

    `window` (start_week, end_week) overrides settings.playoff_window -- lets the
    dashboard's candidate-window dropdown reuse this same machinery for every
    selectable window, not just the shipped default.
    """
    weeks = fantasy_weeks(settings)
    start, end = window if window is not None else (settings.playoff_window.start_week, settings.playoff_window.end_week)
    window_weeks = range(start, end + 1)

    game_dates = schedule.team_game_dates.get(team_abbr, [])
    games_by_week: dict[int, int] = {}
    window_dates: list[date] = []
    for week_number in window_weeks:
        monday, sunday = weeks[week_number]
        in_week = [d for d in game_dates if monday <= d <= sunday]
        games_by_week[week_number] = len(in_week)
        window_dates.extend(in_week)

    window_dates.sort()
    return games_by_week, window_dates


def _normalize_playoff_score(team_games: int, league_games: Iterable[int]) -> float:
    """Min-max normalize one team's playoff-window game count against the league.

    Degenerate case (every team has the same count, e.g. a tiny/uniform fixture)
    has a zero denominator; the plan calls that a wash, not a tiebreak, so it
    returns the midpoint 0.5 rather than dividing by zero or fabricating a rank.
    """
    values = list(league_games)
    league_min, league_max = min(values), max(values)
    if league_max == league_min:
        return 0.5
    return (team_games - league_min) / (league_max - league_min)


def playoff_profile(
    team_abbr: str,
    schedule: Schedule | ScheduleUnavailable,
    settings: Settings,
    window: tuple[int, int] | None = None,
) -> PlayoffProfile | UnavailableProfile:
    """A team's games-by-week, total, back-to-back count, and normalized schedule
    score (0-1, relative to every team in this same schedule) inside the playoff
    window (or `window`, an explicit (start_week, end_week) override for the
    dashboard's candidate-window dropdown).
    """
    if isinstance(schedule, ScheduleUnavailable):
        return UnavailableProfile()

    games_by_week, window_dates = _team_playoff_window(team_abbr, schedule, settings, window)

    # back-to-back = games on consecutive calendar dates, mirroring
    # backend/src/ninecat/warehouse/nba_schedule.py's back_to_backs_in_range;
    # both dates must fall inside the window, so a pair straddling the
    # window's start/end edge (one date in, one date out) does not count
    b2b_count = sum(
        1 for prev, curr in zip(window_dates, window_dates[1:]) if curr - prev == timedelta(days=1)
    )

    league_games = (
        len(_team_playoff_window(team, schedule, settings, window)[1]) for team in schedule.team_game_dates
    )
    score = _normalize_playoff_score(len(window_dates), league_games)

    return PlayoffProfile(
        games_by_week=games_by_week,
        playoff_games=len(window_dates),
        playoff_b2b_count=b2b_count,
        playoff_schedule_score=score,
    )


def league_playoff_game_counts(
    schedule: Schedule | ScheduleUnavailable, settings: Settings, window: tuple[int, int] | None = None
) -> dict[str, int]:
    """Raw total playoff-window games per team, for Task 11 to normalize into 0-1 scores."""
    if isinstance(schedule, ScheduleUnavailable):
        return {}

    return {
        team: len(_team_playoff_window(team, schedule, settings, window)[1])
        for team in schedule.team_game_dates
    }
