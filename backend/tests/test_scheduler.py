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
from pathlib import Path

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
from ninecat.models import JobRun, NbaTeam


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
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_schedule",
        lambda session, season: calls.append("schedule"),
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_averages",
        lambda session, season: calls.append("averages"),
    )
    monkeypatch.setattr(
        "ninecat.jobs.scheduler.sync_player_positions",
        lambda session, season: calls.append("positions"),
    )

    # session is never touched by the stubs above, only passed through
    nightly_warehouse_sync(session=object())

    assert calls == ["schedule", "averages", "positions"]


def test_nightly_warehouse_sync_position_sync_failure_is_non_fatal(monkeypatch, caplog):
    # positions runs last and must not be able to roll back schedule/averages'
    # already-succeeded work, or fail the job -- it's logged and swallowed
    _require_postgres()
    job_name = "test_nightly_position_failure"
    nba_team_id = 999003

    def _stub_schedule(session, season):
        session.add(NbaTeam(nba_team_id=nba_team_id, name="Test Team", abbreviation="TST"))

    def _stub_averages(session, season):
        pass

    def _stub_positions(session, season):
        raise RuntimeError("boom-position")

    monkeypatch.setattr("ninecat.jobs.scheduler.sync_schedule", _stub_schedule)
    monkeypatch.setattr("ninecat.jobs.scheduler.sync_player_averages", _stub_averages)
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
