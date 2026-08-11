from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ninecat.config import get_settings

# explicit naming convention so alembic autogenerate emits stable, predictable
# constraint/index names instead of dialect-generated ones that drift between runs
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base every ORM model inherits from; carries the shared naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@lru_cache
def get_engine() -> Engine:
    # cached: one engine (and its connection pool) per process
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a SQLAlchemy session, committing on success."""
    session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
