from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ninecat.db import Base


class YahooApiCache(Base):
    """A cached Yahoo Fantasy API response, keyed per-user by a hash of the request path."""

    __tablename__ = "yahoo_api_cache"
    # one cached row per (user, path): the gateway upserts this row rather than
    # ever inserting a duplicate for a re-fetched path
    __table_args__ = (UniqueConstraint("user_id", "path_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # sha256 of the resource path, not the path itself -- keeps the key a fixed
    # short size regardless of how long/parameterized a Yahoo resource path gets
    path_hash: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
