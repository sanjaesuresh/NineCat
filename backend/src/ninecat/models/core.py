from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ninecat.db import Base


class User(Base):
    """A person who has connected a Yahoo Fantasy account."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    yahoo_guid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class YahooToken(Base):
    """A user's Yahoo OAuth refresh/access token pair (one per user)."""

    __tablename__ = "yahoo_tokens"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # unique=True enforces the one-token-per-user relationship at the db level;
    # cascade so deleting a user deletes their token rather than orphaning it
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class League(Base):
    """A Yahoo fantasy league synced into NineCat."""

    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    yahoo_league_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    num_teams: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring_type: Mapped[str] = mapped_column(Text, nullable=False)
    settings_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Team(Base):
    """A team within a synced league; optionally the connected user's own team."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # index=True: league_id is a non-unique FK, queried on every "teams in a league" lookup
    league_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    yahoo_team_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # nullable: yahoo teams without a custom logo have no url; a sentinel would be worse than NULL
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_users_team: Mapped[bool] = mapped_column(nullable=False, default=False)
    # SET NULL (not CASCADE): a team is owned by its league first; losing the
    # linked user should un-claim the team, not delete it
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class RosterSlot(Base):
    """A player rostered on a team, as last synced from Yahoo."""

    __tablename__ = "roster_slots"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    yahoo_player_key: Mapped[str] = mapped_column(Text, nullable=False)
    player_name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[str] = mapped_column(Text, nullable=False)
    injury_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
