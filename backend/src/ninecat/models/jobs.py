from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ninecat.db import Base


class JobRun(Base):
    """One execution record of a scheduled background job, for observability."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # index=True: the scheduler/ops view filters run history by job name
    job_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # nullable: unset while the job is still "running"
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "running" | "success" | "failed"
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
