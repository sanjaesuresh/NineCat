"""Syncs Yahoo Fantasy League/Team/Roster/Standings data into NineCat's database.

Every write here is an idempotent upsert (or, for roster slots, a full
delete-then-insert replace) keyed off the yahoo_* natural key. This is
required, not just nice-to-have: YahooGateway may commit the session
mid-request when a Yahoo token rotation happens, so this module can never
hold an un-upserted invariant across a client call -- each write must be
safe to have landed (or not) independent of any other.

TODO(Task 13): sync_user_leagues does not determine which team belongs to the
connected user. Yahoo's user-scoped leagues collection carries no
is_owned_by_current_login flag, and matching by manager display name is
unreliable (renames, collisions). sync_league_detail instead accepts an
explicit users_team_key parameter; Task 13 will source that from a client
addition that resolves the user's own team keys. Until then, Team.user_id
stays NULL and Team.is_users_team stays False for teams synced without it.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ninecat.models import League, RosterSlot, Standing, Team
from ninecat.yahoo.parsers import LeagueInfo, LeagueSettings, RosterEntry, StandingEntry, TeamInfo


class _ClientLike(Protocol):
    """The slice of YahooClient this module needs; a test double can satisfy
    this without going through a gateway."""

    def get_user_leagues(self) -> list[LeagueInfo]: ...
    def get_league_settings(self, league_key: str) -> LeagueSettings: ...
    def get_league_teams(self, league_key: str) -> list[TeamInfo]: ...
    def get_team_roster(self, team_key: str) -> list[RosterEntry]: ...
    def get_standings(self, league_key: str) -> list[StandingEntry]: ...


def sync_user_leagues(session: Session, client: _ClientLike, user_id: int) -> list[League]:
    """Upsert League rows for every NBA league the user is in.

    Cheap and safe to poll often: only name/season/num_teams/scoring_type are
    touched. settings_json is deliberately untouched here -- it's populated by
    the heavier, per-league sync_league_detail instead. user_id is accepted
    for interface symmetry with sync_league_detail / future per-user scoping;
    it isn't written anywhere yet since League has no owner column.
    """
    del user_id  # not yet used -- see module docstring TODO
    leagues: list[League] = []
    for info in client.get_user_leagues():
        league = session.scalars(
            select(League).where(League.yahoo_league_key == info.league_key)
        ).one_or_none()
        if league is None:
            # settings_json is NOT NULL; seeded empty until sync_league_detail fills it in
            league = League(
                yahoo_league_key=info.league_key,
                name=info.name,
                season=int(info.season),
                num_teams=info.num_teams,
                scoring_type=info.scoring_type,
                settings_json={},
            )
            session.add(league)
        else:
            league.name = info.name
            league.season = int(info.season)
            league.num_teams = info.num_teams
            league.scoring_type = info.scoring_type
        league.synced_at = func.now()
        leagues.append(league)

    session.flush()
    return leagues


def sync_league_detail(
    session: Session,
    client: _ClientLike,
    league_id: int,
    users_team_key: str | None = None,
) -> None:
    """Refresh one league's settings, teams, standings, and every team's roster.

    Order matters: teams must be upserted (and flushed, for their ids) before
    standings/rosters can reference them; League.synced_at is set last so a
    row that reads synced_at knows the whole detail sync completed.
    """
    league = session.get(League, league_id)
    if league is None:
        raise ValueError(f"League {league_id} not found")

    settings = client.get_league_settings(league.yahoo_league_key)
    league.settings_json = asdict(settings)

    teams_by_key: dict[str, Team] = {}
    for info in client.get_league_teams(league.yahoo_league_key):
        team = session.scalars(
            select(Team).where(Team.yahoo_team_key == info.team_key)
        ).one_or_none()
        is_match = users_team_key is not None and info.team_key == users_team_key
        if team is None:
            team = Team(
                league_id=league.id,
                yahoo_team_key=info.team_key,
                name=info.name,
                logo_url=info.logo_url,
                is_users_team=is_match,
            )
            session.add(team)
        else:
            team.name = info.name
            team.logo_url = info.logo_url
            # only touch is_users_team when a users_team_key was actually passed --
            # otherwise a detail-only re-sync would blow away a flag set earlier.
            # user_id is never written here (per controller decision: ownership
            # linking is Task 13's job, not this sync's)
            if users_team_key is not None:
                team.is_users_team = is_match
        teams_by_key[info.team_key] = team
    session.flush()  # assign ids to newly-created teams before standings/rosters use them

    for entry in client.get_standings(league.yahoo_league_key):
        team = teams_by_key.get(entry.team_key)
        if team is None:
            continue  # defensive: a standings entry for a team outside the teams list
        standing = session.scalars(
            select(Standing).where(Standing.league_id == league.id, Standing.team_id == team.id)
        ).one_or_none()
        if standing is None:
            standing = Standing(league_id=league.id, team_id=team.id, rank=entry.rank, wins=entry.wins, losses=entry.losses, ties=entry.ties)
            session.add(standing)
        else:
            standing.rank = entry.rank
            standing.wins = entry.wins
            standing.losses = entry.losses
            standing.ties = entry.ties
        standing.synced_at = func.now()

    # fetch every team's roster BEFORE deleting anything: the gateway may commit
    # the session mid-request on a token rotation, so if a later team's fetch
    # raised after an earlier team's rows were already deleted, that team would
    # be left with an empty (and durably committed) roster. Collecting all
    # reads first means a failure here leaves every team's prior roster intact.
    rosters_by_team_key = {team_key: client.get_team_roster(team_key) for team_key in teams_by_key}

    for team_key, team in teams_by_key.items():
        # full-roster replace, not per-row upsert: a dropped player has no upsert
        # key to match against, so diffing old vs new would still need this same
        # delete -- replace is simplest and the (team_id, yahoo_player_key)
        # unique constraint makes leftover duplicates impossible either way
        session.execute(delete(RosterSlot).where(RosterSlot.team_id == team.id))
        for entry in rosters_by_team_key[team_key]:
            session.add(
                RosterSlot(
                    team_id=team.id,
                    yahoo_player_key=entry.player_key,
                    player_name=entry.name,
                    position=entry.selected_position,
                    injury_status=entry.injury_status,
                )
            )

    league.synced_at = func.now()
    session.flush()
