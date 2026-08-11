import os
from collections.abc import Generator

import pytest
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
# matches backend/docker-compose.yml's postgres service, so it also works when
# docker compose is up and there's no exported DATABASE_URL
_DOCKER_DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:54329/postgres"


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
    get_engine.cache_clear()
