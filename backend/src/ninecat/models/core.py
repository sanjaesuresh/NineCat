from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
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


class Standing(Base):
    """A team's rank/record snapshot within a league, as last synced from Yahoo."""

    __tablename__ = "standings"
    # one snapshot row per team per league: the sync upserts this row rather
    # than ever inserting a duplicate for a re-synced league
    __table_args__ = (UniqueConstraint("league_id", "team_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    league_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, nullable=False)
    ties: Mapped[int] = mapped_column(Integer, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RosterSlot(Base):
    """A player rostered on a team, as last synced from Yahoo."""

    __tablename__ = "roster_slots"
    # sync's idempotency key for the full-roster delete-then-insert replace;
    # matches the constraint the migration creates at the db level
    __table_args__ = (UniqueConstraint("team_id", "yahoo_player_key"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    yahoo_player_key: Mapped[str] = mapped_column(Text, nullable=False)
    player_name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[str] = mapped_column(Text, nullable=False)
    injury_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    # yahoo's editorial_team_abbr (e.g. "LAL"), sent on every roster entry;
    # nullable since not every caller populates it -- gives a roster-slot-to-
    # NBA-team path that doesn't depend on the name-matched PlayerIdMap
    nba_team_abbr: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FantasyWeek(Base):
    """A league's fantasy week date range, parsed from Yahoo or derived when absent.

    The scoreboard parser currently extracts only the week number -- Yahoo's
    week_start/week_end are neither parsed nor present in our fixtures -- so
    every piece of weekly math (games this week, streaming days) is blocked on
    having a date range. date_source records whether the range is Yahoo-
    authoritative or a best-effort derivation, so the UI can be honest about it.
    """

    __tablename__ = "fantasy_weeks"
    # one date range per league per week; upserted in place, never duplicated
    # by a later re-parse or re-derivation
    __table_args__ = (UniqueConstraint("league_id", "week"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    league_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    # nullable together: a week can be known (from the scoreboard) before its
    # dates are resolved (date resolution is a separate step) -- a dateless row
    # with a null source is how "known but not yet dated" is represented, rather
    # than forcing a fabricated placeholder date
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # "yahoo" (parsed from the scoreboard payload) or "derived" (computed from
    # a configured season start plus the week number); null iff both dates are
    # null
    date_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WeekResult(Base):
    """A completed fantasy week's per-category totals and outcome, for one team.

    Nothing historical is stored today: standings are an overwritten snapshot
    and roster slots are deleted and re-inserted on every sync, so week data is
    otherwise lost permanently as the season runs. This table is written by a
    later sync step (out of scope here) that observes a completed week; this
    migration only lands the shape.
    """

    __tablename__ = "week_results"
    # one result row per league per week per team; re-observing an already-
    # completed week upserts in place rather than duplicating
    __table_args__ = (UniqueConstraint("league_id", "week", "team_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    league_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    # keyed by stat_id (JSON object keys are always strings) -> yahoo's raw stat
    # value string; mirrors MatchupTeam.category_totals and follows the same
    # parsed-Yahoo-shape-as-JSONB convention as League.settings_json
    category_totals: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # "win" | "loss" | "tie", from this team's own perspective
    result: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
