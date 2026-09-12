import os
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from ninecat.config import get_settings
from ninecat.db import get_engine

# dummy values for the five non-database secrets: not real credentials, just enough
# for pydantic-settings validation to pass on a machine/CI with no .env at all
_DUMMY_REQUIRED_ENV = {
    "YAHOO_CLIENT_ID": "dummy-yahoo-client-id",
    "YAHOO_CLIENT_SECRET": "dummy-yahoo-client-secret",
    "YAHOO_REDIRECT_URI": "https://example.invalid/oauth/callback",
    "TOKEN_ENCRYPTION_KEY": "dummy-token-encryption-key",
    "SESSION_SECRET": "dummy-session-secret",
}
# same docker compose postgres service as dev, but a DEDICATED database: the dev
# database ("postgres") carries committed rows -- dev-login seed, e2e runs, and
# (phase 3 on) real synced schedule and projection data -- that poison the
# suite's shared-population assertions (the README's old cleanup dance, whose
# nba_teams delete also cascaded away real synced games). the suite now points
# at "postgres_test", created and migrated on demand by _test_database below.
# an exported DATABASE_URL still overrides this (CI, or deliberately targeting
# another database).
_DOCKER_DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://postgres:postgres@localhost:54329/postgres_test"
)

_BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> Generator[None, None, None]:
    """Create the dedicated test database if missing and migrate it to head.

    Never fails the run when postgres is down -- db_session skips per-test in
    that case, exactly as before. Runs once per session, before any test.
    """
    url = make_url(os.environ.get("DATABASE_URL", _DOCKER_DEFAULT_DATABASE_URL))
    admin_engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("select 1 from pg_database where datname = :name"),
                {"name": url.database},
            ).scalar()
            if not exists:
                # CREATE DATABASE can't be parameterized; url.database comes from
                # our own constant or the operator's DATABASE_URL, not user input
                conn.execute(text(f'create database "{url.database}"'))
    except OperationalError:
        return  # postgres unreachable: let db_session skip with its message
    finally:
        admin_engine.dispose()

    # alembic's env.py resolves the url through get_settings(), so point the
    # process env at the test database (and backfill the non-db secrets for a
    # machine with no .env) just for the migration, then restore everything
    saved = {
        key: os.environ.get(key) for key in ("DATABASE_URL", *_DUMMY_REQUIRED_ENV)
    }
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    for key, value in _DUMMY_REQUIRED_ENV.items():
        os.environ.setdefault(key, value)
    get_settings.cache_clear()
    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
        command.upgrade(alembic_cfg, "head")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()
    yield


@pytest.fixture(autouse=True)
def _dummy_required_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # makes the suite hermetic: create_app() calls get_settings() (main.py's CORS
    # setup) even for unrelated tests like test_health.py, so without this, a fresh
    # clone/CI with no .env fails the whole suite on missing required settings.
    # test_config.py's own monkeypatch.setenv calls run after this fixture (same
    # monkeypatch instance) and simply overwrite these dummies.
    for key, value in _DUMMY_REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    if "DATABASE_URL" not in os.environ:
        monkeypatch.setenv("DATABASE_URL", _DOCKER_DEFAULT_DATABASE_URL)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Generator[None, None, None]:
    # tests in this suite monkeypatch env vars to exercise Settings; clearing the
    # lru_cache before and after each test keeps that isolated from other tests
    # (including db_session below, which must see this test's own env, not a
    # Settings instance built from a previous test's monkeypatched values)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """A SQLAlchemy session bound to a per-test transaction that always rolls back.

    Skips (rather than failing) when Postgres is unreachable, so the rest of the
    suite — config tests in particular — still runs on a machine without docker up.
    """
    engine = get_engine()
    try:
        connection = engine.connect()
    except OperationalError as exc:
        # never interpolate the raw database_url into a skip message that lands in CI
        # logs — it carries the db password; hide_password=True keeps host/port/dbname
        # (useful for debugging "which database were we trying to reach") but drops it
        redacted_url = make_url(get_settings().database_url).render_as_string(hide_password=True)
        pytest.skip(f"Postgres unreachable at {redacted_url}: {exc}")

    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = session_factory()

    try:
        yield session
    finally:
        session.close()
        # roll back the outer transaction so nothing a test writes is ever persisted
        transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _reset_engine_cache() -> Generator[None, None, None]:
    # get_engine() is lru_cached; drop it after each test so a later test that
    # monkeypatches DATABASE_URL doesn't reuse a stale engine/connection pool
    yield
    # dispose before clearing: cache_clear only drops our reference, it does not
    # close the pool's sockets, so without this every test leaks its connections
    # and a full run exhausts postgres max_connections -- which surfaces as tests
    # SKIPPING with "too many clients already" rather than failing, silently
    # hollowing out the suite
    try:
        get_engine().dispose()
    except Exception:  # engine unbuildable (e.g. a test pointed DATABASE_URL at nothing)
        pass
    get_engine.cache_clear()
