"""Nightly warehouse sync job, run outside any HTTP request via APScheduler."""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ninecat.auth.routes import DEV_LEAGUE_KEY
from ninecat.config import get_settings
from ninecat.db import get_engine
from ninecat.models import League, Team, YahooToken
from ninecat.models.jobs import JobRun
from ninecat.sync.free_agents import sync_league_free_agents
from ninecat.warehouse.nba_schedule import sync_schedule
from ninecat.warehouse.player_positions import sync_player_index, sync_player_positions
from ninecat.warehouse.player_stats import sync_player_averages
from ninecat.yahoo.client import YahooClient
from ninecat.yahoo.gateway import YahooGateway

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


def _leagues_with_yahoo_user(session: Session) -> list[tuple[League, int]]:
    """One (league, user_id) pair per real (non-dev) league that has at least
    one linked user with a stored yahoo token.

    Any such user's client can sync the league-wide free-agent snapshot --
    it's not user-scoped data -- so the first linked user found per league is
    used rather than syncing the same league once per user who happens to
    share it. The dev league is excluded: it has no real yahoo data behind it.
    """
    rows = session.execute(
        select(League, Team.user_id)
        .join(Team, Team.league_id == League.id)
        .join(YahooToken, YahooToken.user_id == Team.user_id)
        .where(League.yahoo_league_key != DEV_LEAGUE_KEY)
    ).all()
    by_league_id: dict[int, tuple[League, int]] = {}
    for league, user_id in rows:
        by_league_id.setdefault(league.id, (league, user_id))
    return list(by_league_id.values())


def _sync_free_agents(session: Session) -> None:
    """Refresh the free-agent snapshot for every real league with a live
    yahoo link.

    Wrapped per-league (not just once for the whole step, unlike the other
    steps above): this genuinely loops over many independent leagues, so one
    league's gateway failure (a revoked token, a yahoo outage) must not stop
    the scan of every other league.
    """
    for league, user_id in _leagues_with_yahoo_user(session):
        try:
            client = YahooClient(YahooGateway(session, user_id))
            result = sync_league_free_agents(session, client, league)
            logger.info(
                "sync_free_agents league=%s wrote %d (%d unmapped)",
                league.yahoo_league_key,
                result.wrote,
                result.unmapped,
            )
        except Exception:
            logger.exception(
                "nightly_warehouse_sync: sync_free_agents failed for league=%s, continuing",
                league.yahoo_league_key,
            )


def nightly_warehouse_sync(session: Session) -> None:
    """Sync the current season's NBA schedule, then player averages, then
    positions, then every real league's free-agent snapshot.

    Order matters twice over: sync_player_averages links each player to the
    NbaTeam row sync_schedule creates, so the schedule must be synced first;
    and sync_player_positions runs before free agents so a rookie free agent
    created this same run already has a position by the time the snapshot
    write needs one. free_agents runs LAST -- it's the only step scoped to
    individual leagues rather than the whole warehouse, and depends on
    everything above (schedule/averages/positions) already existing for
    id-mapping and stat-basis purposes downstream. A position-sync failure is
    caught here (not left to propagate to run_job) so it can't roll back the
    schedule/averages work that already succeeded -- it's logged and the job
    still reports success.

    Each step's row count is logged at INFO, always (not just on zero) --
    JobRun itself only tracks running/success/failed, and `fn` here has no
    access to the JobRun row to write into (run_job constructs it internally),
    so counts live in the log rather than a new column. This is deliberate:
    a schedule sync returning 0 games is EXPECTED before a new season's
    schedule publishes, and must read differently in the logs than "synced
    1200 games" -- not be indistinguishable success in either case.
    """
    season = get_settings().current_season
    schedule_count = sync_schedule(session, season)
    logger.info(
        "nightly_warehouse_sync: sync_schedule upserted %d game rows for season %s",
        schedule_count,
        season,
    )
    averages_count = sync_player_averages(session, season)
    logger.info(
        "nightly_warehouse_sync: sync_player_averages upserted %d rows for season %s",
        averages_count,
        season,
    )
    # identity creation for rostered players no stats feed has seen yet
    # (rookies, players who sat out the whole prior season) -- pre-season this
    # is the only source that can put them on the draft board. non-fatal for
    # the same reason positions is, and it must not stop positions from running
    try:
        index_created = sync_player_index(session, season)
        logger.info(
            "nightly_warehouse_sync: sync_player_index created %d players for season %s",
            index_created,
            season,
        )
    except Exception:
        logger.exception("nightly_warehouse_sync: sync_player_index failed, continuing")
    try:
        position_result = sync_player_positions(session, season)
        logger.info(
            "nightly_warehouse_sync: sync_player_positions matched=%d skipped=%d for season %s",
            position_result.matched,
            position_result.skipped,
            season,
        )
    except Exception:
        logger.exception(
            "nightly_warehouse_sync: sync_player_positions failed, continuing"
        )
    # non-fatal at the step level too (see module docstring); _sync_free_agents
    # itself is already non-fatal per-league, so this only guards against a
    # failure in the league-selection query itself (e.g. the db going away)
    try:
        _sync_free_agents(session)
    except Exception:
        logger.exception("nightly_warehouse_sync: sync_free_agents step failed, continuing")


def register_jobs(scheduler: BaseScheduler) -> BaseScheduler:
    """Register the nightly warehouse sync at 04:00 US/Eastern and return scheduler."""
    scheduler.add_job(
        lambda: run_job("nightly_warehouse_sync", nightly_warehouse_sync),
        trigger=CronTrigger(hour=4, minute=0, timezone="America/New_York"),
        id="nightly_warehouse_sync",
    )
    return scheduler
