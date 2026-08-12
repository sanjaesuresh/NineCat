"""Nightly warehouse sync job, run outside any HTTP request via APScheduler."""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session, sessionmaker

from ninecat.config import get_settings
from ninecat.db import get_engine
from ninecat.models.jobs import JobRun
from ninecat.warehouse.nba_schedule import sync_schedule
from ninecat.warehouse.player_stats import sync_player_averages

logger = logging.getLogger(__name__)

# generous but bounded: these are plain warehouse-sync errors (bad rows, a
# flaky nba_api call), not secrets, so a full message is safe -- just capped
# so one huge traceback string can't bloat the job_runs table
_ERROR_MAX_LEN = 2000


def run_job(job_name: str, fn: Callable[[Session], None]) -> None:
    """Run fn(session) under its own session/transaction, recording a JobRun row.

    Opens a fresh session rather than reusing get_session()'s request-scoped one,
    since scheduled jobs run on the scheduler's own thread, outside any request.
    Never propagates, on any path: a failing fn, or the database itself being
    unreachable, is logged here instead of raised, so one bad job can't kill the
    scheduler thread or stop sibling jobs from running.
    """
    session = None
    job_run = JobRun(job_name=job_name, status="running")
    try:
        # session/engine construction lives in this same try so a db that's
        # down (connection refused, DNS failure, ...) is caught here too --
        # "never propagates on any path" has to include this step, not just the writes
        session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False
        )
        session = session_factory()
        session.add(job_run)
        # commit immediately so the "running" row is visible for the job's whole duration
        session.commit()
    except Exception:
        # can't even reach the db to record that the job started -- nothing to roll
        # back to, so just log and bail; this is the "db is down" case, and it must
        # never propagate out to the scheduler thread
        logger.exception(
            "run_job(%s): could not open a session / record the running JobRun row", job_name
        )
        if session is not None:
            session.close()
        return

    try:
        fn(session)

        job_run.status = "success"
        job_run.finished_at = datetime.now(timezone.utc)
        # one commit persists both fn's work and the success status together
        session.commit()
    except Exception as exc:
        # class name + message, not just str(exc): some exceptions (e.g. a bare
        # OperationalError with no args) stringify to nothing useful on their own
        error_text = f"{type(exc).__name__}: {exc}"[:_ERROR_MAX_LEN]
        # .exception (not .error): this is the common failure path, so it should
        # carry a traceback in the log, not just the one-line message
        logger.exception("run_job(%s): fn raised", job_name)
        try:
            # undo fn's partial writes -- a failed job must not leave half-synced data
            session.rollback()
            job_run.status = "failed"
            job_run.finished_at = datetime.now(timezone.utc)
            job_run.error = error_text
            session.commit()
        except Exception:
            # this bookkeeping write can itself fail (db dropped mid-job); that's the
            # one failure mode that would otherwise destroy the JobRun row silently,
            # so it gets its own log record rather than sharing the one above
            logger.exception("run_job(%s): failed to record the failed JobRun row", job_name)
    finally:
        session.close()


def nightly_warehouse_sync(session: Session) -> None:
    """Sync the current season's NBA schedule, then player averages.

    Order matters: sync_player_averages links each player to the NbaTeam row
    sync_schedule creates, so the schedule must be synced first.
    """
    season = get_settings().current_season
    sync_schedule(session, season)
    sync_player_averages(session, season)


def register_jobs(scheduler: BaseScheduler) -> BaseScheduler:
    """Register the nightly warehouse sync at 04:00 US/Eastern and return scheduler."""
    scheduler.add_job(
        lambda: run_job("nightly_warehouse_sync", nightly_warehouse_sync),
        trigger=CronTrigger(hour=4, minute=0, timezone="America/New_York"),
        id="nightly_warehouse_sync",
    )
    return scheduler
