from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ninecat.db import Base


class AdvisorCache(Base):
    """A validated advisor response, keyed by a hash of its normalized input.

    Deliberately not the Yahoo cache table: that one is user-scoped and
    Yahoo-shaped, and overloading it would couple two unrelated lifecycles
    (plan A3).

    There is no user_id here on purpose. Because the prompt contains no
    identifiers, the same input from two users is genuinely the same question,
    so the answer is safe to share -- and the absence of the column is what
    keeps that true (plan B6).
    """

    __tablename__ = "advisor_cache"
    # one row per distinct question; the cache writer upserts rather than ever
    # inserting a second row for the same hash
    __table_args__ = (UniqueConstraint("request_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # sha256 over the normalized request (feature, model, prompt version,
    # shortlist, context) -- see advisor/cache.py for exactly what goes in
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # feature and model are already folded into request_hash; stored separately
    # so entries can be counted or purged per feature/model without rehashing
    feature: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
