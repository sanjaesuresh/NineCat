from datetime import date, timedelta

from sqlalchemy import select

from ninecat.models.core import FantasyWeek, League, Team
from ninecat.warehouse.fantasy_weeks import (
    DATE_SOURCE_DERIVED,
    DATE_SOURCE_YAHOO,
    derive_week_range,
    resolve_week,
    week_date_range,
)


def _make_league(db_session, key_suffix: str) -> League:
    # mirrors test_models_core.py's _make_league_and_team helper, kept local
    # so this file stays within its own file boundary
    league = League(
        yahoo_league_key=f"nba.l.fw-{key_suffix}",
        name=f"League {key_suffix}",
        season=2026,
        num_teams=10,
        scoring_type="head",
        settings_json={},
    )
    db_session.add(league)
    db_session.flush()
    db_session.add(
        Team(
            league_id=league.id,
            yahoo_team_key=f"nba.l.fw-{key_suffix}.t.1",
            name="Team",
            is_users_team=False,
        )
    )
    db_session.flush()
    return league


def _fetch_weeks(db_session, league: League) -> list[FantasyWeek]:
    # scoped to this test's own league_id, never a bare select(FantasyWeek) --
    # the suite is pollution-proof (FU1) and this must not reintroduce a
    # global-row assertion
    return list(
        db_session.execute(
            select(FantasyWeek).where(FantasyWeek.league_id == league.id)
        ).scalars()
    )


# --- derive_week_range: hand-computed arithmetic -----------------------------


def test_derive_week_range_week_1_starts_on_season_starts_monday():
    season_start = date(2025, 10, 20)  # already a monday

    start, end = derive_week_range(1, season_start=season_start)

    assert start == date(2025, 10, 20)
    assert end == date(2025, 10, 26)  # inclusive monday-sunday


def test_derive_week_range_week_2_crosses_a_month_boundary():
    season_start = date(2025, 10, 20)

    start, end = derive_week_range(2, season_start=season_start)

    assert start == date(2025, 10, 27)
    assert end == date(2025, 11, 2)


def test_derive_week_range_week_5_is_28_days_after_week_1():
    season_start = date(2025, 10, 20)

    week1_start, _ = derive_week_range(1, season_start=season_start)
    start, end = derive_week_range(5, season_start=season_start)

    assert start == week1_start + timedelta(days=28)
    assert start == date(2025, 11, 17)
    assert end == date(2025, 11, 23)


def test_derive_week_range_snaps_a_mid_week_anchor_back_to_its_monday():
    # a season opener is frequently mid-week (e.g. a wednesday tip-off);
    # week 1 must still start on that week's monday, not the wednesday itself
    season_start = date(2025, 10, 22)  # a wednesday

    start, end = derive_week_range(1, season_start=season_start)

    assert start == date(2025, 10, 20)
    assert end == date(2025, 10, 26)


# --- resolve_week: persistence, precedence, idempotency ----------------------


def test_resolve_week_derives_and_persists_when_no_yahoo_dates_supplied(db_session):
    league = _make_league(db_session, "derive-1")

    row = resolve_week(db_session, league, week=1)

    expected_start, expected_end = derive_week_range(1)
    assert row.start_date == expected_start
    assert row.end_date == expected_end
    assert row.date_source == DATE_SOURCE_DERIVED
    assert _fetch_weeks(db_session, league) == [row]


def test_resolve_week_yahoo_dates_are_stored_with_yahoo_source(db_session):
    league = _make_league(db_session, "yahoo-1")

    row = resolve_week(
        db_session, league, week=3, yahoo_start=date(2026, 1, 12), yahoo_end=date(2026, 1, 18)
    )

    assert row.start_date == date(2026, 1, 12)
    assert row.end_date == date(2026, 1, 18)
    assert row.date_source == DATE_SOURCE_YAHOO


def test_resolve_week_yahoo_dates_overwrite_a_prior_derivation(db_session):
    league = _make_league(db_session, "overwrite-1")
    resolve_week(db_session, league, week=1)  # derived first

    row = resolve_week(
        db_session, league, week=1, yahoo_start=date(2025, 10, 20), yahoo_end=date(2025, 10, 26)
    )

    assert row.date_source == DATE_SOURCE_YAHOO
    assert row.start_date == date(2025, 10, 20)
    assert row.end_date == date(2025, 10, 26)
    # upsert in place, not a second row
    weeks = _fetch_weeks(db_session, league)
    assert len(weeks) == 1
    assert weeks[0].id == row.id


def test_resolve_week_a_later_derivation_never_clobbers_yahoo_dates(db_session):
    league = _make_league(db_session, "no-clobber-1")
    yahoo_row = resolve_week(
        db_session, league, week=1, yahoo_start=date(2025, 10, 20), yahoo_end=date(2025, 10, 26)
    )

    # re-resolving with no yahoo dates falls back to deriving, which must lose
    row = resolve_week(db_session, league, week=1)

    assert row.date_source == DATE_SOURCE_YAHOO
    assert row.start_date == yahoo_row.start_date
    assert row.end_date == yahoo_row.end_date
    weeks = _fetch_weeks(db_session, league)
    assert len(weeks) == 1


def test_resolve_week_is_idempotent_no_duplicate_rows_no_drift(db_session):
    league = _make_league(db_session, "idempotent-1")

    first = resolve_week(db_session, league, week=2)
    second = resolve_week(db_session, league, week=2)

    assert first.start_date == second.start_date
    assert first.end_date == second.end_date
    assert first.date_source == second.date_source
    weeks = _fetch_weeks(db_session, league)
    assert len(weeks) == 1


def test_resolve_week_treats_a_lone_yahoo_date_as_not_supplied(db_session):
    # half a range isn't usable -- only start OR only end must fall back to
    # deriving rather than persisting a one-sided range
    league = _make_league(db_session, "lone-date-1")

    row = resolve_week(db_session, league, week=1, yahoo_start=date(2025, 10, 20))

    assert row.date_source == DATE_SOURCE_DERIVED


# --- week_date_range: the "is this honest" helper -----------------------------


def test_week_date_range_returns_none_when_week_never_resolved(db_session):
    league = _make_league(db_session, "range-none-1")

    assert week_date_range(db_session, league, 1) is None


def test_week_date_range_returns_none_when_week_known_but_dateless(db_session):
    league = _make_league(db_session, "range-none-2")
    db_session.add(FantasyWeek(league_id=league.id, week=4))
    db_session.flush()

    assert week_date_range(db_session, league, 4) is None


def test_week_date_range_reports_derived_true_for_a_derived_week(db_session):
    league = _make_league(db_session, "range-derived-1")
    resolve_week(db_session, league, week=1)

    result = week_date_range(db_session, league, 1)

    expected_start, expected_end = derive_week_range(1)
    assert result is not None
    assert result.is_derived is True
    assert result.start_date == expected_start
    assert result.end_date == expected_end


def test_week_date_range_reports_derived_false_for_a_yahoo_week(db_session):
    league = _make_league(db_session, "range-yahoo-1")
    resolve_week(
        db_session, league, week=1, yahoo_start=date(2025, 10, 20), yahoo_end=date(2025, 10, 26)
    )

    result = week_date_range(db_session, league, 1)

    assert result is not None
    assert result.is_derived is False
    assert result.start_date == date(2025, 10, 20)
    assert result.end_date == date(2025, 10, 26)
