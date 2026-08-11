from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ninecat.db import Base


class NbaTeam(Base):
    """An NBA team, keyed by NBA.com's own team id (stable across seasons)."""

    __tablename__ = "nba_teams"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # natural key from NBA.com (e.g. 1610612738); unique so sync_schedule can
    # upsert on it instead of duplicating a team on every re-sync
    nba_team_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    abbreviation: Mapped[str] = mapped_column(Text, nullable=False)


class NbaGame(Base):
    """A single scheduled NBA game, upserted from nba_api's season schedule."""

    __tablename__ = "nba_games"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # NBA.com's own game id (e.g. "0022500001") is the natural key and the
    # ON CONFLICT target, so re-running sync_schedule never duplicates a game
    nba_game_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # index=True: games_in_range/back_to_backs_in_range both filter on a date range
    game_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    season: Mapped[str] = mapped_column(Text, nullable=False)
    # index=True on both: games_in_range matches a team as either home or away
    home_team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("nba_teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    away_team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("nba_teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
