"""Tests for the nightly job scheduler: register_jobs' cron, run_job's success/
failure bookkeeping, nightly_warehouse_sync's ordering, the scheduler_enabled
gate, and the JobRun migration.

run_job opens its OWN session (bound directly to get_engine()), separate from
the db_session fixture's per-test transaction -- so anything it commits is
really committed and would otherwise survive db_session's rollback and leak
into later tests. Every test that calls run_job cleans up its own rows
explicitly (by a unique job_name / nba_team_id) in a finally block, using a
second fresh session opened the same way to both verify and clean up.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from ninecat.config import get_settings
from ninecat.db import get_engine
from ninecat.jobs.scheduler import nightly_warehouse_sync, register_jobs, run_job
from ninecat.main import create_app
from ninecat.models import JobRun, League, NbaTeam, Team, User, YahooToken
from ninecat.sync.free_agents import FreeAgentSyncResult
from ninecat.warehouse.player_positions import PositionSyncResult


def _fresh_session() -> Session:
    """A session bound directly to get_engine(), independent of db_session's
    transaction -- used to see and clean up what run_job actually committed."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)()


def _require_postgres() -> None:
    # skip (not fail) on a machine/CI without postgres up, matching db_session's
    # own skip behavior elsewhere in this suite
    try:
        get_engine().connect().close()
    except OperationalError as exc:
        pytest.skip(f"Postgres unreachable: {exc}")


def _cleanup_job_run(job_name: str) -> None:
    session = _fresh_session()
    try:
        session.execute(delete(JobRun).where(JobRun.job_name == job_name))
        session.commit()
    finally:
        session.close()


def _cleanup_nba_team(nba_team_id: int) -> None:
    session = _fresh_session()
    try:
        session.execute(delete(NbaTeam).where(NbaTeam.nba_team_id == nba_team_id))
        session.commit()
    finally:
        session.close()


# --- register_jobs ---


def test_register_jobs_registers_nightly_cron_at_0400_america_new_york():
    scheduler = BackgroundScheduler()

    result = register_jobs(scheduler)

    assert result is scheduler
    job = scheduler.get_job("nightly_warehouse_sync")
    assert job is not None

    trigger = job.trigger
    assert isinstance(trigger, CronTrigger)
    fields_by_name = {field.name: field for field in trigger.fields}
    # inspect the compiled expression's value, not any string repr
    assert fields_by_name["hour"].expressions[0].first == 4
    assert fields_by_name["minute"].expressions[0].first == 0
    assert trigger.timezone.key == "America/New_York"


# --- run_job ---


def test_run_job_success_records_success_and_persists_fn_writes():
    _require_postgres()
    job_name = "test_run_job_success"
    nba_team_id = 999001

    def fn(session: Session) -> None:
        session.add(NbaTeam(nba_team_id=nba_team_id, name="Test Team", abbreviation="TST"))

    try:
        run_job(job_name, fn)

        verify = _fresh_session()
        try:
            job_run = verify.execute(
                select(JobRun).where(JobRun.job_name == job_name)
            ).scalar_one()
            team = verify.execute(
                select(NbaTeam).where(NbaTeam.nba_team_id == nba_team_id)
            ).scalar_one_or_none()
        finally:
            verify.close()

        assert job_run.status == "success"
        assert job_run.finished_at is not None
        assert job_run.error is None
        assert team is not None
    finally:
        _cleanup_job_run(job_name)
        _cleanup_nba_team(nba_team_id)


def test_run_job_failure_records_failure_rolls_back_and_does_not_propagate():
    _require_postgres()
    job_name = "test_run_job_failure"
    nba_team_id = 999002

    def failing_fn(session: Session) -> None:
        # this write must not survive: run_job rolls back on failure
        session.add(NbaTeam(nba_team_id=nba_team_id, name="Test Team", abbreviation="TST"))
        session.flush()
        raise RuntimeError("boom")

    try:
        # must not raise -- one failed job cannot kill the caller/scheduler
        run_job(job_name, failing_fn)

        verify = _fresh_session()
        try:
            job_run = verify.execute(
                select(JobRun).where(JobRun.job_name == job_name)
            ).scalar_one()
            team = verify.execute(
                select(NbaTeam).where(NbaTeam.nba_team_id == nba_team_id)
            ).scalar_one_or_none()
        finally:
            verify.close()

        assert job_run.status == "failed"
        assert job_run.finished_at is not None
        assert job_run.error is not None
        assert "boom" in job_run.error
        # fn's partial write was rolled back, not committed
        assert team is None

        # a second run_job (same job_name) still works after the prior failure
        run_job(job_name, lambda session: None)

        verify = _fresh_session()
        try:
            runs = (
                verify.execute(
                    select(JobRun).where(JobRun.job_name == job_name).order_by(JobRun.id)
                )
                .scalars()
                .all()
            )
        finally:
            verify.close()

        assert len(runs) == 2
        assert runs[-1].status == "success"
    finally:
        _cleanup_job_run(job_name)
        _cleanup_nba_team(nba_team_id)


class _AlwaysFailingSession:
    """Stands in for a real Session when the database itself is unreachable --
    every DB-touching call raises, simulating an outage regardless of which
    statement run_job happens to issue first."""

    def add(self, obj: object) -> None:
        pass

    def commit(self) -> None:
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_run_job_swallows_database_outage_and_logs(monkeypatch, caplog):
    # simulate "the database is down": every session obtained by run_job fails
    # on first use, regardless of get_engine() -- exercises the outer
    # try/except around the initial "running" JobRun write, not just fn's
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sessionmaker",
        lambda **kwargs: (lambda: _AlwaysFailingSession()),
    )

    with caplog.at_level(logging.ERROR, logger="ninecat.jobs.scheduler"):
        # must return normally -- a db outage must never propagate out of run_job
        run_job("test_run_job_db_down", lambda session: None)

    assert any(record.name == "ninecat.jobs.scheduler" for record in caplog.records)


# --- nightly_warehouse_sync ---


def test_nightly_warehouse_sync_runs_schedule_then_averages_then_positions(monkeypatch):
    calls: list[str] = []
    # return realistic types (int / int / PositionSyncResult), matching the
    # real sync functions -- nightly_warehouse_sync now logs these return
    # values (row-count observability), so a stub returning None would make
    # that logging call blow up on a real run
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_schedule",
        lambda session, season: calls.append("schedule") or 0,
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_averages",
        lambda session, season: calls.append("averages") or 0,
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_index",
        lambda session, season: calls.append("index") or 0,
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_positions",
        lambda session, season: calls.append("positions") or PositionSyncResult(),
    )

    # session is never touched by the stubs above, only passed through
    nightly_warehouse_sync(session=object())

    # index runs after averages (identity creation for rookies/sat-out players
    # the stats feeds can't see) and before positions, which stays last
    assert calls == ["schedule", "averages", "index", "positions"]


def test_nightly_warehouse_sync_uses_current_season_setting_not_hardcoded(monkeypatch):
    """Proves the season each step syncs comes from Settings.current_season,
    not a hardcoded/independently-derived string -- a season rollover must be
    a config change, not a code edit."""
    seasons_used: dict[str, str] = {}

    def _stub_schedule(session, season):
        seasons_used["schedule"] = season
        return 0

    def _stub_averages(session, season):
        seasons_used["averages"] = season
        return 0

    def _stub_positions(session, season):
        seasons_used["positions"] = season
        return PositionSyncResult()

    def _stub_index(session, season):
        seasons_used["index"] = season
        return 0

    monkeypatch.setattr("ninecat.jobs.scheduler.sync_schedule", _stub_schedule)
    monkeypatch.setattr("ninecat.jobs.scheduler.sync_player_averages", _stub_averages)
    monkeypatch.setattr("ninecat.jobs.scheduler.sync_player_index", _stub_index)
    monkeypatch.setattr("ninecat.jobs.scheduler.sync_player_positions", _stub_positions)
    # a season deliberately unlike the real default ("2025-26"), so this test
    # can't accidentally pass just because it matches Settings' default
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.get_settings",
        lambda: SimpleNamespace(current_season="2099-00"),
    )

    nightly_warehouse_sync(session=object())

    assert seasons_used == {
        "schedule": "2099-00",
        "averages": "2099-00",
        "index": "2099-00",
        "positions": "2099-00",
    }


def test_nightly_warehouse_sync_logs_row_counts_including_zero(monkeypatch, caplog):
    """A schedule sync returning 0 games (expected in the off-season, before a
    new season's schedule publishes) must be visible in the log, distinct
    from a healthy nonzero sync -- not silently indistinguishable success."""
    monkeypatch.setattr("ninecat.jobs.scheduler.sync_schedule", lambda session, season: 0)
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_averages", lambda session, season: 450
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_index", lambda session, season: 3
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_positions",
        lambda session, season: PositionSyncResult(matched=450, skipped=2),
    )

    with caplog.at_level(logging.INFO, logger="ninecat.jobs.scheduler"):
        nightly_warehouse_sync(session=object())

    assert "sync_schedule upserted 0 game rows" in caplog.text
    assert "sync_player_averages upserted 450 rows" in caplog.text
    assert "sync_player_index created 3 players" in caplog.text
    assert "sync_player_positions matched=450 skipped=2" in caplog.text


def test_nightly_warehouse_sync_index_sync_failure_is_non_fatal(monkeypatch, caplog):
    # same rationale as the positions non-fatal rule: identity creation is an
    # enrichment step and must never take down the schedule/averages the draft
    # engine depends on, nor stop positions from running after it
    calls: list[str] = []
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_schedule", lambda session, season: 0
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_averages", lambda session, season: 0
    )

    def _boom_index(session, season):
        raise RuntimeError("boom-index")

    monkeypatch.setattr("ninecat.jobs.scheduler.sync_player_index", _boom_index)
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_positions",
        lambda session, season: calls.append("positions") or PositionSyncResult(),
    )

    with caplog.at_level(logging.ERROR, logger="ninecat.jobs.scheduler"):
        nightly_warehouse_sync(session=object())

    assert "sync_player_index failed" in caplog.text
    assert calls == ["positions"]


def test_nightly_warehouse_sync_position_sync_failure_is_non_fatal(monkeypatch, caplog):
    # positions runs last and must not be able to roll back schedule/averages'
    # already-succeeded work, or fail the job -- it's logged and swallowed
    _require_postgres()
    job_name = "test_nightly_position_failure"
    nba_team_id = 999003

    def _stub_schedule(session, season):
        session.add(NbaTeam(nba_team_id=nba_team_id, name="Test Team", abbreviation="TST"))
        return 1

    def _stub_averages(session, season):
        return 0

    def _stub_positions(session, season):
        raise RuntimeError("boom-position")

    monkeypatch.setattr("ninecat.jobs.scheduler.sync_schedule", _stub_schedule)
    monkeypatch.setattr("ninecat.jobs.scheduler.sync_player_averages", _stub_averages)
    monkeypatch.setattr("ninecat.jobs.scheduler.sync_player_index", lambda session, season: 0)
    monkeypatch.setattr("ninecat.jobs.scheduler.sync_player_positions", _stub_positions)

    try:
        with caplog.at_level(logging.ERROR, logger="ninecat.jobs.scheduler"):
            run_job(job_name, nightly_warehouse_sync)

        verify = _fresh_session()
        try:
            job_run = verify.execute(
                select(JobRun).where(JobRun.job_name == job_name)
            ).scalar_one()
            team = verify.execute(
                select(NbaTeam).where(NbaTeam.nba_team_id == nba_team_id)
            ).scalar_one_or_none()
        finally:
            verify.close()

        # the job as a whole still succeeds, and schedule's write survives --
        # only the position-sync exception is caught and logged
        assert job_run.status == "success"
        assert team is not None
        assert "boom-position" in caplog.text
    finally:
        _cleanup_job_run(job_name)
        _cleanup_nba_team(nba_team_id)


# --- sync_free_agents step (WP5) ---


def _stub_first_four_steps(monkeypatch, calls: list[str] | None = None) -> None:
    """Stubs schedule/averages/index/positions to no-ops (optionally recording
    into `calls`), isolating a test to just the free-agents step."""
    record = (lambda name: calls.append(name)) if calls is not None else (lambda name: None)
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_schedule", lambda session, season: record("schedule") or 0
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_averages",
        lambda session, season: record("averages") or 0,
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_index", lambda session, season: record("index") or 0
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_positions",
        lambda session, season: record("positions") or PositionSyncResult(),
    )


def test_nightly_warehouse_sync_runs_free_agents_last(monkeypatch):
    calls: list[str] = []
    _stub_first_four_steps(monkeypatch, calls)
    league = SimpleNamespace(id=1, yahoo_league_key="466.l.99")
    monkeypatch.setattr(
        "ninecat.jobs.scheduler._leagues_with_yahoo_user", lambda session: [(league, 7)]
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_league_free_agents",
        lambda session, client, lg: calls.append("free_agents")
        or FreeAgentSyncResult(fetched=1, wrote=1, unmapped=0),
    )

    nightly_warehouse_sync(session=object())

    # free_agents runs after positions -- it's the only step scoped to
    # individual leagues, and depends on everything above already existing
    assert calls == ["schedule", "averages", "index", "positions", "free_agents"]


def test_nightly_warehouse_sync_logs_free_agent_counts_per_league(monkeypatch, caplog):
    _stub_first_four_steps(monkeypatch)
    league = SimpleNamespace(id=1, yahoo_league_key="466.l.99")
    monkeypatch.setattr(
        "ninecat.jobs.scheduler._leagues_with_yahoo_user", lambda session: [(league, 7)]
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_league_free_agents",
        lambda session, client, lg: FreeAgentSyncResult(fetched=10, wrote=8, unmapped=2),
    )

    with caplog.at_level(logging.INFO, logger="ninecat.jobs.scheduler"):
        nightly_warehouse_sync(session=object())

    assert "sync_free_agents league=466.l.99 wrote 8 (2 unmapped)" in caplog.text


def test_nightly_warehouse_sync_free_agents_failure_for_one_league_is_non_fatal(
    monkeypatch, caplog
):
    """One league's sync raising must not stop the scan of the others, and
    must not fail the job -- mirrors sync_player_index's own non-fatal rule,
    but per-league since this step genuinely loops over many leagues."""
    _stub_first_four_steps(monkeypatch)
    boom_league = SimpleNamespace(id=1, yahoo_league_key="466.l.boom")
    ok_league = SimpleNamespace(id=2, yahoo_league_key="466.l.ok")
    monkeypatch.setattr(
        "ninecat.jobs.scheduler._leagues_with_yahoo_user",
        lambda session: [(boom_league, 7), (ok_league, 8)],
    )

    synced: list[str] = []

    def _sync(session, client, lg):
        if lg.yahoo_league_key == "466.l.boom":
            raise RuntimeError("boom-free-agents")
        synced.append(lg.yahoo_league_key)
        return FreeAgentSyncResult(fetched=0, wrote=0, unmapped=0)

    monkeypatch.setattr("ninecat.jobs.scheduler.sync_league_free_agents", _sync)

    with caplog.at_level(logging.ERROR, logger="ninecat.jobs.scheduler"):
        nightly_warehouse_sync(session=object())  # must not raise

    assert "boom-free-agents" in caplog.text
    assert synced == ["466.l.ok"]


def test_leagues_with_yahoo_user_skips_dev_league_and_dedupes_by_league(db_session):
    """_leagues_with_yahoo_user must exclude the dev league (no real yahoo
    data behind it) and return exactly one (league, user_id) pair even when
    two linked users share the same real league."""
    from ninecat.auth.routes import DEV_LEAGUE_KEY
    from ninecat.jobs.scheduler import _leagues_with_yahoo_user

    def _seed_user_with_token(guid: str) -> User:
        user = User(yahoo_guid=guid, display_name=guid)
        db_session.add(user)
        db_session.flush()
        db_session.add(
            YahooToken(
                user_id=user.id,
                encrypted_refresh_token="enc",
                access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        db_session.flush()
        return user

    real_league = League(
        yahoo_league_key="466.l.real", name="Real League", season=2026, num_teams=2,
        scoring_type="head", settings_json={},
    )  # fmt: skip
    dev_league = League(
        yahoo_league_key=DEV_LEAGUE_KEY, name="Dev League", season=2026, num_teams=2,
        scoring_type="head", settings_json={},
    )  # fmt: skip
    db_session.add_all([real_league, dev_league])
    db_session.flush()

    user_a = _seed_user_with_token("guid-fa-a")
    user_b = _seed_user_with_token("guid-fa-b")
    dev_user = _seed_user_with_token("guid-fa-dev")
    db_session.add_all(
        [
            Team(league_id=real_league.id, yahoo_team_key="466.l.real.t.1", name="A", user_id=user_a.id),
            Team(league_id=real_league.id, yahoo_team_key="466.l.real.t.2", name="B", user_id=user_b.id),
            Team(league_id=dev_league.id, yahoo_team_key=f"{DEV_LEAGUE_KEY}.t.1", name="Dev", user_id=dev_user.id),
        ]
    )  # fmt: skip
    db_session.flush()

    pairs = _leagues_with_yahoo_user(db_session)

    assert len(pairs) == 1
    league, user_id = pairs[0]
    assert league.yahoo_league_key == "466.l.real"
    assert user_id in (user_a.id, user_b.id)


# --- scheduler_enabled gate ---


def test_create_app_does_not_start_scheduler_when_disabled(monkeypatch):
    # default is False, and _dummy_required_settings_env doesn't set it, but
    # be explicit so this test doesn't depend on that fixture's behavior
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    get_settings.cache_clear()
    assert get_settings().scheduler_enabled is False

    def _fail_if_constructed(*args, **kwargs):
        raise AssertionError("BackgroundScheduler must not be constructed when disabled")

    monkeypatch.setattr("ninecat.main.BackgroundScheduler", _fail_if_constructed)

    app = create_app()

    assert app is not None


# --- migration ---

BACKEND_DIR = Path(__file__).resolve().parents[1]
PRIOR_HEAD = "0c78fbbd5f0f"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_migration_upgrade_downgrade_upgrade_is_clean_with_single_head():
    _require_postgres()

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1

    command.downgrade(cfg, PRIOR_HEAD)
    command.upgrade(cfg, "head")

    # leaves the db back at head so it doesn't strand the rest of the suite
    assert ScriptDirectory.from_config(cfg).get_current_head() is not None
