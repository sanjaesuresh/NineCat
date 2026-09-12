"""Backfill WeekResult rows from a historical league's Yahoo scoreboard.

One-shot, re-runnable (invoked directly, like the projections import -- not a
nightly job): for a given historical league key, ensures League/Team rows
exist, walks the season's weeks, and upserts a WeekResult row per team per
COMPLETED week. As a free by-product, every week's Yahoo-supplied dates are
fed through warehouse.fantasy_weeks.resolve_week -- settling WP1 debt (b)'s
derived-vs-yahoo comparison with a real season of week boundaries.

Every write here is an idempotent upsert, same requirement as sync/league_sync.py:
a re-run must produce identical rows, not duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.engine.matchup import compare_matchup
from ninecat.engine.weekly import WeeklyProjection
from ninecat.engine.zscores import CATEGORIES
from ninecat.models.core import League, Team, WeekResult
from ninecat.warehouse.fantasy_weeks import derive_week_range, resolve_week
from ninecat.yahoo.parsers import LeagueInfo, LeagueSettings, Matchup, TeamInfo

# a season this backfill would never plausibly run past -- guards the
# through_week=None walk against looping forever on a client double that
# never returns an empty scoreboard
_SAFETY_MAX_WEEKS = 30

# yahoo's stat display_name for the fixed nine-cat h2h format this product
# supports (canonical order: FG%, FT%, 3PM, PTS, REB, AST, ST, BLK, TO) ->
# engine.zscores.CATEGORIES' key. A league whose settings don't carry exactly
# these nine (auction/points leagues, out of scope) simply never completes a
# week below, since _parse_team_totals requires all nine to be present.
_DISPLAY_NAME_TO_CATEGORY = {
    "FG%": "fg_pct",
    "FT%": "ft_pct",
    "3PTM": "tpm",
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "ST": "stl",
    "BLK": "blk",
    "TO": "tov",
}


class _ClientLike(Protocol):
    """The slice of YahooClient this module needs; a test double can satisfy
    this without going through a gateway."""

    def get_league_info(self, league_key: str) -> LeagueInfo: ...
    def get_league_settings(self, league_key: str) -> LeagueSettings: ...
    def get_league_teams(self, league_key: str) -> list[TeamInfo]: ...
    def get_scoreboard(self, league_key: str, week: int | None = None) -> list[Matchup]: ...


@dataclass(frozen=True)
class WeekDateComparison:
    """One week's yahoo-supplied dates vs. what derive_week_range alone would
    have said -- the debt-(b) boundary report this backfill settles as a
    by-product. agrees is None when yahoo supplied no dates to compare against
    (nothing to agree or disagree with)."""

    week: int
    yahoo_start: date | None
    yahoo_end: date | None
    derived_start: date
    derived_end: date
    agrees: bool | None


@dataclass(frozen=True)
class SkippedWeek:
    week: int
    reason: str  # "no_matchups" | "empty_totals" | "future_end_date"


@dataclass
class BackfillReport:
    # not frozen, unlike the value-record dataclasses above -- this is built
    # incrementally as the week-by-week walk progresses, not constructed once
    weeks_written: list[int] = field(default_factory=list)
    weeks_skipped: list[SkippedWeek] = field(default_factory=list)
    rows_upserted: int = 0
    date_comparisons: list[WeekDateComparison] = field(default_factory=list)


def _ensure_league_and_teams(
    session: Session, client: _ClientLike, league_key: str
) -> tuple[League, dict[str, Team]]:
    """League + Team rows for `league_key`, creating them the first time this
    historical league is touched. Mirrors sync/league_sync.py's upsert idioms
    (select-by-natural-key then create-or-update) but skips standings/rosters
    entirely -- this backfill only needs a Team row to exist per yahoo team so
    WeekResult rows have somewhere to point their team_id FK; it never assumes
    a user link the way sync_league_detail's is_users_team resolution does.
    """
    league = session.scalars(
        select(League).where(League.yahoo_league_key == league_key)
    ).one_or_none()
    if league is None:
        # user_leagues is scoped to the CURRENT game (live-verified: the
        # renew-chain historical league never appears there), so fetch the
        # league's own metadata header directly instead
        info = client.get_league_info(league_key)
        league = League(
            yahoo_league_key=info.league_key,
            name=info.name,
            season=int(info.season),
            num_teams=info.num_teams,
            scoring_type=info.scoring_type,
            settings_json={},
        )
        session.add(league)
        session.flush()

    teams_by_key: dict[str, Team] = {}
    for info in client.get_league_teams(league_key):
        team = session.scalars(
            select(Team).where(Team.yahoo_team_key == info.team_key)
        ).one_or_none()
        if team is None:
            team = Team(
                league_id=league.id,
                yahoo_team_key=info.team_key,
                name=info.name,
                logo_url=info.logo_url,
                is_users_team=False,
            )
            session.add(team)
        else:
            team.name = info.name
            team.logo_url = info.logo_url
        teams_by_key[info.team_key] = team
    session.flush()  # assign ids to newly-created teams before WeekResult rows reference them
    return league, teams_by_key


def _category_map(settings: LeagueSettings) -> dict[int, str]:
    return {
        c.stat_id: _DISPLAY_NAME_TO_CATEGORY[c.display_name]
        for c in settings.categories
        if c.display_name in _DISPLAY_NAME_TO_CATEGORY
    }


def _parse_team_totals(
    category_totals: dict[int, str], stat_id_to_category: dict[int, str]
) -> dict[str, float] | None:
    """One MatchupTeam's raw stat_id->string totals, translated to canonical
    category keys. None means incomplete -- an empty/unparseable value (yahoo
    hasn't finalized the week yet) or a category missing outright -- and the
    caller skips the whole week rather than write a partial result.
    """
    parsed: dict[str, float] = {}
    for stat_id, raw_value in category_totals.items():
        category = stat_id_to_category.get(stat_id)
        if category is None:
            continue
        if raw_value in ("", "-"):
            return None
        try:
            parsed[category] = float(raw_value)
        except ValueError:
            return None
    if len(parsed) != len(CATEGORIES):
        return None
    return parsed


def _totals_projection(totals: dict[str, float]) -> WeeklyProjection:
    """Wrap a real (non-projected) totals dict in a WeeklyProjection shell so
    engine.matchup.compare_matchup -- which owns the one tov sign inversion --
    can be reused for "who actually won more categories" instead of
    re-implementing that rule here. games/components/player_games are unused
    placeholders; only .totals is read by compare_matchup for this purpose.
    """
    return WeeklyProjection(
        totals=totals,
        components={"fgm": 0.0, "fga": 0.0, "ftm": 0.0, "fta": 0.0},
        games=0.0,
        player_games={},
    )


def _upsert_week_result(
    session: Session,
    *,
    league_id: int,
    team_id: int,
    week: int,
    category_totals: dict[str, float],
    result: str,
) -> None:
    insert_stmt = pg_insert(WeekResult).values(
        league_id=league_id,
        team_id=team_id,
        week=week,
        category_totals=category_totals,
        result=result,
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[WeekResult.league_id, WeekResult.week, WeekResult.team_id],
        set_={
            "category_totals": insert_stmt.excluded.category_totals,
            "result": insert_stmt.excluded.result,
            # onupdate=func.now() does NOT fire for ON CONFLICT updates
            # (SQLAlchemy only applies onupdate to ORM-driven UPDATEs), same
            # fix as resolve_week/sync_schedule
            "synced_at": func.now(),
        },
    )
    session.execute(stmt)


def backfill_week_results(
    session: Session,
    client: _ClientLike,
    league_key: str,
    *,
    through_week: int | None = None,
) -> BackfillReport:
    """Backfill WeekResult rows for `league_key`'s completed weeks.

    through_week, when given, is the exact week range to walk (1..through_week
    inclusive) -- every week in that range is attempted regardless of what an
    earlier week did. Left None, the walk starts at week 1 and stops the first
    time a week isn't a real, complete, past week (no matchups, unparseable/
    empty totals, or an end date not yet in the past) -- the natural "we've
    reached the edge of the season" signal for a completed historical league,
    capped at _SAFETY_MAX_WEEKS so a misbehaving client double can't loop
    forever.
    """
    league, teams_by_key = _ensure_league_and_teams(session, client, league_key)
    stat_id_to_category = _category_map(client.get_league_settings(league_key))

    report = BackfillReport()
    today = date.today()
    if through_week is not None:
        last_week = through_week
    else:
        # bound the walk by the league's own end_week: yahoo answers an
        # out-of-range week with no scoreboard section at all (live-verified,
        # a parse error rather than an empty list), so walking blind past the
        # end is not survivable. safety cap stays for a metadata gap.
        end_week = client.get_league_info(league_key).end_week
        last_week = end_week if end_week is not None else _SAFETY_MAX_WEEKS

    week = 1
    while week <= last_week:
        matchups = client.get_scoreboard(league_key, week=week)
        if not matchups:
            report.weeks_skipped.append(SkippedWeek(week=week, reason="no_matchups"))
            if through_week is None:
                break
            week += 1
            continue

        # every matchup in a given week shares one fantasy-week date range;
        # take the first non-null pair for resolve_week and the debt-(b) report
        yahoo_start = next((m.week_start for m in matchups if m.week_start), None)
        yahoo_end = next((m.week_end for m in matchups if m.week_end), None)
        week_range = resolve_week(session, league, week, yahoo_start=yahoo_start, yahoo_end=yahoo_end)

        derived_start, derived_end = derive_week_range(week)
        report.date_comparisons.append(
            WeekDateComparison(
                week=week,
                yahoo_start=yahoo_start,
                yahoo_end=yahoo_end,
                derived_start=derived_start,
                derived_end=derived_end,
                agrees=(
                    (yahoo_start == derived_start and yahoo_end == derived_end)
                    if yahoo_start is not None and yahoo_end is not None
                    else None
                ),
            )
        )

        if week_range.end_date >= today:
            report.weeks_skipped.append(SkippedWeek(week=week, reason="future_end_date"))
            if through_week is None:
                break
            week += 1
            continue

        # parse every matchup's both sides before writing anything: a week is
        # completed as a whole or not at all, so one team's unparseable/empty
        # totals must skip the entire week, not just that one matchup
        totals_by_matchup: list[tuple[Matchup, dict[str, dict[str, float]]]] = []
        incomplete = False
        for matchup in matchups:
            if len(matchup.teams) != 2:
                continue  # defensive: a bye-week single-team "matchup" has no opponent to compare
            totals_by_team_key = {
                t.team_key: _parse_team_totals(t.category_totals, stat_id_to_category)
                for t in matchup.teams
            }
            if any(totals is None for totals in totals_by_team_key.values()):
                incomplete = True
                break
            totals_by_matchup.append((matchup, totals_by_team_key))  # type: ignore[arg-type]

        if incomplete:
            report.weeks_skipped.append(SkippedWeek(week=week, reason="empty_totals"))
            if through_week is None:
                break
            week += 1
            continue

        for matchup, totals_by_team_key in totals_by_matchup:
            team_a_key, team_b_key = (t.team_key for t in matchup.teams)
            totals_a, totals_b = totals_by_team_key[team_a_key], totals_by_team_key[team_b_key]
            comparison = compare_matchup(_totals_projection(totals_a), _totals_projection(totals_b))
            mine_wins, their_wins = comparison.projected_score
            if mine_wins == their_wins:
                result_a = result_b = "tie"
            elif mine_wins > their_wins:
                result_a, result_b = "win", "loss"
            else:
                result_a, result_b = "loss", "win"

            for team_key, totals, result in (
                (team_a_key, totals_a, result_a),
                (team_b_key, totals_b, result_b),
            ):
                team = teams_by_key.get(team_key)
                if team is None:
                    continue  # defensive: a scoreboard team outside the teams list
                _upsert_week_result(
                    session,
                    league_id=league.id,
                    team_id=team.id,
                    week=week,
                    category_totals=totals,
                    result=result,
                )
                report.rows_upserted += 1

        report.weeks_written.append(week)
        week += 1

    session.flush()
    return report
