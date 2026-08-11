"""Typed, resource-oriented view of the Yahoo Fantasy API.

Stays thin on purpose: every method composes a resource path, calls
YahooGateway.get (which owns auth/caching/retry), and hands the raw dict to
parsers.py for unwrapping. No httpx, no cache, no Yahoo JSON shape knowledge
belongs here.
"""

from __future__ import annotations

from typing import Protocol

from ninecat.yahoo.parsers import (
    LeagueInfo,
    LeagueSettings,
    Matchup,
    RosterEntry,
    StandingEntry,
    TeamInfo,
    parse_league_settings,
    parse_league_teams,
    parse_scoreboard,
    parse_standings,
    parse_team_roster,
    parse_user_leagues,
)

# cache TTLs, one per resource kind -- how volatile each resource is in practice
# drives the number (league settings rarely change mid-season; scoreboards
# change constantly while games are live)
LEAGUES_CACHE_TTL_SECONDS = 6 * 60 * 60
SETTINGS_CACHE_TTL_SECONDS = 24 * 60 * 60
TEAMS_CACHE_TTL_SECONDS = 6 * 60 * 60
ROSTER_CACHE_TTL_SECONDS = 60 * 60
STANDINGS_CACHE_TTL_SECONDS = 60 * 60
SCOREBOARD_CACHE_TTL_SECONDS = 15 * 60


class _GatewayLike(Protocol):
    def get(self, resource_path: str, cache_ttl_seconds: int) -> dict: ...


class YahooClient:
    """Resource-oriented facade over YahooGateway; returns parsed dataclasses."""

    def __init__(self, gateway: _GatewayLike):
        self._gateway = gateway

    def get_user_leagues(self) -> list[LeagueInfo]:
        raw = self._gateway.get(
            "users;use_login=1/games;game_keys=nba/leagues", LEAGUES_CACHE_TTL_SECONDS
        )
        return parse_user_leagues(raw)

    def get_league_settings(self, league_key: str) -> LeagueSettings:
        raw = self._gateway.get(f"league/{league_key}/settings", SETTINGS_CACHE_TTL_SECONDS)
        return parse_league_settings(raw)

    def get_league_teams(self, league_key: str) -> list[TeamInfo]:
        raw = self._gateway.get(f"league/{league_key}/teams", TEAMS_CACHE_TTL_SECONDS)
        return parse_league_teams(raw)

    def get_team_roster(self, team_key: str) -> list[RosterEntry]:
        raw = self._gateway.get(f"team/{team_key}/roster", ROSTER_CACHE_TTL_SECONDS)
        return parse_team_roster(raw)

    def get_standings(self, league_key: str) -> list[StandingEntry]:
        raw = self._gateway.get(f"league/{league_key}/standings", STANDINGS_CACHE_TTL_SECONDS)
        return parse_standings(raw)

    def get_scoreboard(self, league_key: str, week: int) -> list[Matchup]:
        raw = self._gateway.get(
            f"league/{league_key}/scoreboard;week={week}", SCOREBOARD_CACHE_TTL_SECONDS
        )
        return parse_scoreboard(raw)
