"""Resolve and persist a league's fantasy week date range.

Lives in warehouse/, not sync/: sync/league_sync.py owns calling the yahoo
client and orchestrating a league's writes, and stays off-limits while that
sync is being extended elsewhere; this module never talks to yahoo itself --
it takes already-parsed dates (or none) and either stores them or derives a
range, the same "idempotent upsert plus deterministic derived math, no live
network required" shape as warehouse/nba_schedule.py and
warehouse/player_positions.py.

Every later fantasy-week consumer (weekly projection, streaming optimizer,
matchup API) is meant to call `week_date_range`, not read FantasyWeek rows
directly, so "was this range derived or yahoo-authoritative" stays a single
well-tested rule instead of being re-decided at each call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.config import get_settings
from ninecat.models.core import FantasyWeek, League

# recorded in FantasyWeek.date_source so the UI can tell a real yahoo-supplied
# range from a best-effort guess
DATE_SOURCE_YAHOO = "yahoo"
DATE_SOURCE_DERIVED = "derived"


@dataclass(frozen=True)
class WeekDateRange:
    """A resolved week's inclusive start/end, plus whether it was derived."""

    start_date: date
    end_date: date
    is_derived: bool


def derive_week_range(week: int, season_start: date | None = None) -> tuple[date, date]:
    """Monday-to-Sunday range for fantasy week `week`, counting from the
    configured season start (overridable for tests/callers that need a
    specific anchor rather than the live config).

    Week 1 starts on season_start's own Monday -- season_start itself need not
    fall on a Monday, since a season opener is frequently mid-week -- and each
    later week is a further 7-day block. Deterministic on purpose: no
    date.today() anywhere here, only the configured/passed-in anchor and the
    week number argument, so re-deriving the same week always gives the same
    range.
    """
    anchor = season_start if season_start is not None else get_settings().fantasy_season_start
    monday = anchor - timedelta(days=anchor.weekday())
    start = monday + timedelta(weeks=week - 1)
    end = start + timedelta(days=6)
    return start, end


def resolve_week(
    session: Session,
    league: League,
    week: int,
    *,
    yahoo_start: date | None = None,
    yahoo_end: date | None = None,
) -> FantasyWeek:
    """Persist (idempotent upsert) and return the FantasyWeek row for
    `league`'s `week`.

    yahoo_start/yahoo_end (both must be present -- a lone one is treated as
    "not supplied" since half a range isn't usable) win and are stored with
    date_source="yahoo", overwriting whatever was stored before, including a
    prior derivation. Without both, the range is DERIVED from the configured
    season start and stored with date_source="derived" -- but a derivation
    must never clobber yahoo-supplied dates already on record, since real
    data beats a guess.

    Single atomic ON CONFLICT upsert, not select-then-write: the yahoo gateway
    this feeds from can commit the session mid-request, so a read-then-decide
    window here would be unsafe. The "don't let derived beat yahoo" rule is
    therefore enforced with a conditional WHERE on the upsert itself, not a
    Python-side check.
    """
    if yahoo_start is not None and yahoo_end is not None:
        start_date, end_date, source = yahoo_start, yahoo_end, DATE_SOURCE_YAHOO
    else:
        start_date, end_date = derive_week_range(week)
        source = DATE_SOURCE_DERIVED

    insert_stmt = pg_insert(FantasyWeek).values(
        league_id=league.id,
        week=week,
        start_date=start_date,
        end_date=end_date,
        date_source=source,
    )
    set_ = {
        "start_date": insert_stmt.excluded.start_date,
        "end_date": insert_stmt.excluded.end_date,
        "date_source": insert_stmt.excluded.date_source,
        # onupdate=func.now() on the column does NOT fire for ON CONFLICT
        # updates (SQLAlchemy only applies onupdate to ORM-driven UPDATEs),
        # so it's set explicitly here, same fix as nba_schedule.sync_schedule
        "synced_at": func.now(),
    }
    if source == DATE_SOURCE_YAHOO:
        # yahoo data always wins, regardless of what's already stored
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[FantasyWeek.league_id, FantasyWeek.week], set_=set_
        )
    else:
        # only overwrite if the existing row isn't already yahoo-sourced --
        # a later derivation must never clobber real yahoo dates. postgres
        # skips the update entirely (and the row stays untouched) when this
        # is false, which is exactly "derivation loses to yahoo"
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[FantasyWeek.league_id, FantasyWeek.week],
            set_=set_,
            where=FantasyWeek.date_source.is_distinct_from(DATE_SOURCE_YAHOO),
        )
    session.execute(stmt)
    session.flush()

    # re-select rather than trust a RETURNING row: when the WHERE above skips
    # the update (yahoo dates already on record), postgres returns no row, so
    # this is the one path that always finds the current, correct row either way
    return session.execute(
        select(FantasyWeek).where(FantasyWeek.league_id == league.id, FantasyWeek.week == week)
    ).scalar_one()


def week_date_range(session: Session, league: League, week: int) -> WeekDateRange | None:
    """The stored date range for `league`'s `week`, plus whether it was derived.

    Returns None when the week has never been resolved (no FantasyWeek row)
    or is known but not yet dated (a scoreboard-only row with null dates) --
    callers must treat both the same way: there is no range to show yet.
    """
    row = session.execute(
        select(FantasyWeek).where(FantasyWeek.league_id == league.id, FantasyWeek.week == week)
    ).scalar_one_or_none()
    if row is None or row.start_date is None or row.end_date is None:
        return None
    return WeekDateRange(
        start_date=row.start_date,
        end_date=row.end_date,
        is_derived=row.date_source == DATE_SOURCE_DERIVED,
    )
