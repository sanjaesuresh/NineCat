"""Backtest the weekly matchup projection against real, persisted WeekResults.

Answers the phase-2 O1 question honestly: given a completed historical
league's real rosters (as they stood each week), real season averages, and
the real NBA schedule, how often does compare_matchup's predicted category
winner match what actually happened? Deterministic given the DB (backfilled
WeekResults + warehouse schedule/averages) and an injected client -- no clock,
no randomness, and every roster/id-mapping/schedule gap is counted rather than
silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ninecat.engine.matchup import compare_matchup
from ninecat.engine.weekly import WeeklyPlayerRate, WeeklyProjection, project_week
from ninecat.engine.zscores import CATEGORIES
from ninecat.models.core import League, Team, WeekResult
from ninecat.models.warehouse import NbaTeam, PlayerIdMap, PlayerSeasonAverage
from ninecat.warehouse.fantasy_weeks import week_date_range
from ninecat.warehouse.id_mapping import map_yahoo_players
from ninecat.warehouse.nba_schedule import games_in_range
from ninecat.yahoo.parsers import Matchup, RosterEntry


class _ClientLike(Protocol):
    """The slice of YahooClient this module needs; a test double can satisfy
    this without going through a gateway."""

    def get_scoreboard(self, league_key: str, week: int | None = None) -> list[Matchup]: ...
    def get_team_roster_for_week(self, team_key: str, week: int) -> list[RosterEntry]: ...


@dataclass(frozen=True)
class CategoryHitRate:
    """One category's prediction record across every matchup evaluated.

    ties_excluded counts real (nonzero-total) ties -- there is no actual
    winner to predict against, so they're tracked separately from `total`
    rather than silently counted as a miss or a hit.
    """

    predicted_correct: int = 0
    ties_excluded: int = 0
    total: int = 0

    @property
    def hit_rate(self) -> float:
        return self.predicted_correct / self.total if self.total else 0.0


@dataclass(frozen=True)
class TeamWeekUnmapped:
    """How many of one team's rostered players had no usable stat basis for
    a given week -- an id-mapping miss, no season-average row for `season`,
    or an unresolvable NBA team -- and so contributed nothing to that team's
    projection. Never silently dropped; always surfaced here."""

    week: int
    team_key: str
    count: int


@dataclass(frozen=True)
class SkippedBacktestWeek:
    week: int
    reason: str  # "no_week_range" | "team_not_synced" | "missing_actual_result"


@dataclass
class BacktestReport:
    # not frozen -- built incrementally, matchup by matchup, like BackfillReport
    per_category: dict[str, CategoryHitRate] = field(
        default_factory=lambda: {cat: CategoryHitRate() for cat in CATEGORIES}
    )
    overall_correct: int = 0
    overall_total: int = 0
    unmapped_by_team_week: list[TeamWeekUnmapped] = field(default_factory=list)
    weeks_skipped: list[SkippedBacktestWeek] = field(default_factory=list)

    @property
    def overall_hit_rate(self) -> float:
        return self.overall_correct / self.overall_total if self.overall_total else 0.0


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _actual_projection(totals: dict[str, float]) -> WeeklyProjection:
    """Wrap a WeekResult's stored (canonical-keyed, still RAW) totals in a
    WeeklyProjection shell so compare_matchup -- which owns the ONE tov sign
    inversion -- can be reused for "who actually won more categories" instead
    of re-implementing that rule here. `totals` must stay raw (do not invert
    tov here); compare_matchup's _oriented_margin is the only place that
    happens. games/components/player_games are unused placeholders.
    """
    return WeeklyProjection(
        totals=totals,
        components={"fgm": 0.0, "fga": 0.0, "ftm": 0.0, "fta": 0.0},
        games=0.0,
        player_games={},
    )


def _nba_team_id_by_abbr(session: Session) -> dict[str, int]:
    return {t.abbreviation: t.nba_team_id for t in session.execute(select(NbaTeam)).scalars().all()}


def _team_rates(
    session: Session,
    roster: list[RosterEntry],
    season: str,
    abbr_to_nba_id: dict[str, int],
    week_start: date,
    week_end: date,
) -> tuple[list[WeeklyPlayerRate], int]:
    """One team's per-player weekly rates valued on `season`'s real averages,
    plus how many rostered players had no usable stat basis. Mirrors the API
    layer's _team_side assembly (rosters -> rates -> games-in-week), but
    against a fetched roster-for-week + PlayerSeasonAverage rather than
    RosterSlot + the draft board's projection-or-average rows -- there is no
    "projection" for a past season, only what actually happened.
    """
    if not roster:
        return [], 0

    # ensures every yahoo_player_key on this historical roster has a
    # PlayerIdMap row -- these are 466-prefixed historical keys, distinct from
    # whatever the CURRENT season's roster sync already mapped, so this call
    # is very much expected to do real work here, not just find already_mapped
    map_yahoo_players(session, roster)
    session.flush()

    id_map_by_key = {
        m.yahoo_player_key: m
        for m in session.execute(
            select(PlayerIdMap).where(
                PlayerIdMap.yahoo_player_key.in_([r.player_key for r in roster])
            )
        )
        .scalars()
        .all()
    }
    nba_player_ids = {
        m.nba_player_id for m in id_map_by_key.values() if m.nba_player_id is not None
    }
    averages_by_player = (
        {
            row.nba_player_id: row
            for row in session.execute(
                select(PlayerSeasonAverage).where(
                    PlayerSeasonAverage.season == season,
                    PlayerSeasonAverage.nba_player_id.in_(nba_player_ids),
                )
            )
            .scalars()
            .all()
        }
        if nba_player_ids
        else {}
    )

    rates: list[WeeklyPlayerRate] = []
    unmapped = 0
    for entry in roster:
        id_map = id_map_by_key.get(entry.player_key)
        nba_player_id = id_map.nba_player_id if id_map is not None else None
        average = averages_by_player.get(nba_player_id) if nba_player_id is not None else None
        nba_team_id = abbr_to_nba_id.get(entry.nba_team_abbr)
        # any of: no id-map match, no season-average row, or an unresolvable
        # NBA team -- all three mean "no stat basis to project this player
        # on", the same skip the API layer's _team_side applies, but counted
        # here rather than silently contributing zero
        if average is None or nba_team_id is None:
            unmapped += 1
            continue
        games = float(games_in_range(session, nba_team_id, week_start, week_end).count)
        rates.append(
            WeeklyPlayerRate(
                player_key=entry.player_key,
                games=games,
                fgm=average.fgm,
                fga=average.fga,
                ftm=average.ftm,
                fta=average.fta,
                tpm=average.tpm,
                pts=average.pts,
                reb=average.reb,
                ast=average.ast,
                stl=average.stl,
                blk=average.blk,
                tov=average.tov,
            )
        )
    return rates, unmapped


def run_matchup_backtest(
    session: Session, client: _ClientLike, league_key: str, season: str
) -> BacktestReport:
    """Backtest every completed week already backfilled for `league_key`.

    Requires backfill_week_results to have already run for this league (its
    WeekResult rows are the "actual" side of every comparison and also
    determine which weeks are in scope) -- raises if the league was never
    synced at all, since there is nothing to backtest against.
    """
    league = session.execute(
        select(League).where(League.yahoo_league_key == league_key)
    ).scalar_one_or_none()
    if league is None:
        raise ValueError(f"league {league_key!r} has not been synced -- run backfill_week_results first")

    report = BacktestReport()
    weeks = sorted(
        session.execute(
            select(WeekResult.week).where(WeekResult.league_id == league.id).distinct()
        )
        .scalars()
        .all()
    )
    abbr_to_nba_id = _nba_team_id_by_abbr(session)

    for week in weeks:
        week_range = week_date_range(session, league, week)
        if week_range is None:
            report.weeks_skipped.append(SkippedBacktestWeek(week=week, reason="no_week_range"))
            continue

        for matchup in client.get_scoreboard(league_key, week=week):
            if matchup.week != week or len(matchup.teams) != 2:
                continue
            team_a_key, team_b_key = (t.team_key for t in matchup.teams)
            team_a = session.execute(
                select(Team).where(Team.league_id == league.id, Team.yahoo_team_key == team_a_key)
            ).scalar_one_or_none()
            team_b = session.execute(
                select(Team).where(Team.league_id == league.id, Team.yahoo_team_key == team_b_key)
            ).scalar_one_or_none()
            if team_a is None or team_b is None:
                report.weeks_skipped.append(SkippedBacktestWeek(week=week, reason="team_not_synced"))
                continue

            actual_a = session.execute(
                select(WeekResult).where(
                    WeekResult.league_id == league.id, WeekResult.week == week, WeekResult.team_id == team_a.id
                )
            ).scalar_one_or_none()
            actual_b = session.execute(
                select(WeekResult).where(
                    WeekResult.league_id == league.id, WeekResult.week == week, WeekResult.team_id == team_b.id
                )
            ).scalar_one_or_none()
            if actual_a is None or actual_b is None:
                report.weeks_skipped.append(SkippedBacktestWeek(week=week, reason="missing_actual_result"))
                continue

            roster_a = client.get_team_roster_for_week(team_a_key, week)
            roster_b = client.get_team_roster_for_week(team_b_key, week)
            rates_a, unmapped_a = _team_rates(
                session, roster_a, season, abbr_to_nba_id, week_range.start_date, week_range.end_date
            )
            rates_b, unmapped_b = _team_rates(
                session, roster_b, season, abbr_to_nba_id, week_range.start_date, week_range.end_date
            )
            if unmapped_a:
                report.unmapped_by_team_week.append(
                    TeamWeekUnmapped(week=week, team_key=team_a_key, count=unmapped_a)
                )
            if unmapped_b:
                report.unmapped_by_team_week.append(
                    TeamWeekUnmapped(week=week, team_key=team_b_key, count=unmapped_b)
                )

            predicted = compare_matchup(project_week(rates_a), project_week(rates_b))
            actual = compare_matchup(
                _actual_projection(dict(actual_a.category_totals)),
                _actual_projection(dict(actual_b.category_totals)),
            )
            predicted_by_cat = {cv.category: cv for cv in predicted.categories}
            actual_by_cat = {cv.category: cv for cv in actual.categories}

            for category in CATEGORIES:
                hit = report.per_category[category]
                actual_margin = actual_by_cat[category].margin
                if actual_margin == 0:
                    # a genuine tie has no winner to predict against --
                    # excluded from `total`, not counted as a miss
                    report.per_category[category] = CategoryHitRate(
                        predicted_correct=hit.predicted_correct,
                        ties_excluded=hit.ties_excluded + 1,
                        total=hit.total,
                    )
                    continue
                correct = _sign(predicted_by_cat[category].margin) == _sign(actual_margin)
                report.per_category[category] = CategoryHitRate(
                    predicted_correct=hit.predicted_correct + (1 if correct else 0),
                    ties_excluded=hit.ties_excluded,
                    total=hit.total + 1,
                )
                report.overall_total += 1
                if correct:
                    report.overall_correct += 1

    return report
