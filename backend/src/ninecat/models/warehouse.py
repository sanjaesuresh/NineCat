from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
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


class NbaPlayer(Base):
    """An NBA player, keyed by NBA.com's own person id (stable across team changes)."""

    __tablename__ = "nba_players"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # natural key from NBA.com (e.g. 201939); unique so sync_player_averages can
    # upsert on it instead of duplicating a player on every re-sync
    nba_person_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    # NOT unique: two different real players can share a full name (see the
    # ambiguous-match rule in warehouse/id_mapping.py); index=True since name
    # lookups are the common query path
    full_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # nullable: players change teams mid-season and free agents have none;
    # SET NULL (not CASCADE) so losing a team row never deletes the player
    nba_team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("nba_teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class PlayerSeasonAverage(Base):
    """A player's per-game stat averages for one season, upserted from nba_api."""

    __tablename__ = "player_season_averages"
    # one row per player per season: sync_player_averages upserts on this pair
    # rather than ever inserting a duplicate for a re-synced season
    __table_args__ = (UniqueConstraint("nba_player_id", "season"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # CASCADE: a season-average row has no meaning once its player is gone
    nba_player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("nba_players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    season: Mapped[str] = mapped_column(Text, nullable=False)
    games_played: Mapped[int] = mapped_column(Integer, nullable=False)
    # per-game makes/attempts, not bare fg_pct/ft_pct: the engine's volume-weighted
    # z-scores need makes/attempts to combine shooting efficiency with volume
    fgm: Mapped[float] = mapped_column(Float, nullable=False)
    fga: Mapped[float] = mapped_column(Float, nullable=False)
    ftm: Mapped[float] = mapped_column(Float, nullable=False)
    fta: Mapped[float] = mapped_column(Float, nullable=False)
    tpm: Mapped[float] = mapped_column(Float, nullable=False)
    pts: Mapped[float] = mapped_column(Float, nullable=False)
    reb: Mapped[float] = mapped_column(Float, nullable=False)
    ast: Mapped[float] = mapped_column(Float, nullable=False)
    stl: Mapped[float] = mapped_column(Float, nullable=False)
    blk: Mapped[float] = mapped_column(Float, nullable=False)
    tov: Mapped[float] = mapped_column(Float, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PlayerIdMap(Base):
    """Links a Yahoo fantasy player_key to an NbaPlayer, or records it unmatched for manual fixup."""

    __tablename__ = "player_id_maps"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # null = unmatched, pending manual resolution; SET NULL (not CASCADE) so
    # deleting an NbaPlayer row degrades the mapping to unmatched instead of
    # silently deleting the human's yahoo<->nba linkage decision
    nba_player_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("nba_players.id", ondelete="SET NULL"), nullable=True, index=True
    )
    yahoo_player_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # the yahoo name we attempted to match against, kept for auditing/debugging
    # a bad match independent of whatever NbaPlayer.full_name says today
    yahoo_name: Mapped[str] = mapped_column(Text, nullable=False)
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PlayerProjection(Base):
    """A projected per-game stat line for a player/season from one external source.

    Separate from PlayerSeasonAverage (actual results from nba_api) since a
    projection is a forward-looking estimate, not a boxscore fact, and the
    same player/season can have projections from multiple sources at once.
    """

    __tablename__ = "player_projections"
    # one row per player per season per source: import_projections_csv upserts
    # on this triple rather than duplicating a row on every re-import
    __table_args__ = (UniqueConstraint("nba_player_id", "season", "source"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # CASCADE: a projection row has no meaning once its player is gone
    nba_player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("nba_players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    season: Mapped[str] = mapped_column(Text, nullable=False)
    # which projection source produced this row (e.g. "hashtag-basketball");
    # part of the upsert key so multiple sources can coexist for one season
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # projected games for the season, distinct from PlayerSeasonAverage's
    # games_played (an actual count); named explicitly to avoid confusing the two
    projected_games: Mapped[int] = mapped_column(Integer, nullable=False)
    # per-game makes/attempts, not bare fg_pct/ft_pct -- mirrors PlayerSeasonAverage
    # so the engine can treat projected and actual rows the same way
    fgm: Mapped[float] = mapped_column(Float, nullable=False)
    fga: Mapped[float] = mapped_column(Float, nullable=False)
    ftm: Mapped[float] = mapped_column(Float, nullable=False)
    fta: Mapped[float] = mapped_column(Float, nullable=False)
    tpm: Mapped[float] = mapped_column(Float, nullable=False)
    pts: Mapped[float] = mapped_column(Float, nullable=False)
    reb: Mapped[float] = mapped_column(Float, nullable=False)
    ast: Mapped[float] = mapped_column(Float, nullable=False)
    stl: Mapped[float] = mapped_column(Float, nullable=False)
    blk: Mapped[float] = mapped_column(Float, nullable=False)
    tov: Mapped[float] = mapped_column(Float, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
