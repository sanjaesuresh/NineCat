"""Typed, resource-oriented view of the Yahoo Fantasy API.

Stays thin on purpose: every method composes a resource path, calls
YahooGateway.get (which owns auth/caching/retry), and hands the raw dict to
parsers.py for unwrapping. No httpx, no cache, no Yahoo JSON shape knowledge
belongs here.
"""

from __future__ import annotations

from typing import Protocol

from ninecat.yahoo.parsers import (
    DraftResultsPage,
    FreeAgentEntry,
    LeagueInfo,
    LeagueSettings,
    Matchup,
    RosterEntry,
    StandingEntry,
    TeamInfo,
    UserTeamInfo,
    parse_draft_results,
    parse_league_metadata,
    parse_league_players,
    parse_league_settings,
    parse_league_teams,
    parse_scoreboard,
    parse_standings,
    parse_team_roster,
    parse_user_leagues,
    parse_user_teams,
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
# short on purpose: this is client-driven polling (the draft page, not the
# scheduler), so 20s just means N open tabs still cost Yahoo at most one call
# per 20s window -- respectful of Yahoo's rate limits without staling a live pick
DRAFT_CACHE_TTL_SECONDS = 20
# a completed historical week's roster never changes -- unlike ROSTER_CACHE_TTL_SECONDS
# (the "current" roster, which does), so a backtest re-run over the same season
# is effectively free after the first pass
ROSTER_HISTORICAL_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
# free agency moves at daily scale, not by the minute (unlike ROSTER_CACHE_TTL_SECONDS's
# hour) -- this is a nightly-scan resource, so a several-hour TTL is plenty fresh
FREE_AGENTS_CACHE_TTL_SECONDS = 6 * 60 * 60
# yahoo's league players collection pages 25 at a time; this is yahoo's own page size,
# not a tunable choice
FREE_AGENTS_PAGE_SIZE = 25
# a pre-draft league's "all available" pool is close to the entire player universe --
# hundreds of pages -- and this is a background sync, not a UI wait, but it still must
# not be able to loop forever against a misbehaving/mocked gateway
FREE_AGENTS_MAX_PAGES = 40


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

    def get_user_teams(self) -> list[UserTeamInfo]:
        # same TTL as get_league_teams -- rosters/teams don't churn within a day,
        # and this is Task 13's way of discovering which Team row is "mine"
        raw = self._gateway.get(
            "users;use_login=1/games;game_keys=nba/teams", TEAMS_CACHE_TTL_SECONDS
        )
        return parse_user_teams(raw)

    def get_league_info(self, league_key: str) -> LeagueInfo:
        # direct metadata fetch: the user_leagues listing is scoped to the
        # current game, so historical (renew-chain) leagues need this instead
        raw = self._gateway.get(f"league/{league_key}", SETTINGS_CACHE_TTL_SECONDS)
        return parse_league_metadata(raw)

    def get_league_settings(self, league_key: str) -> LeagueSettings:
        raw = self._gateway.get(f"league/{league_key}/settings", SETTINGS_CACHE_TTL_SECONDS)
        return parse_league_settings(raw)

    def get_league_teams(self, league_key: str) -> list[TeamInfo]:
        raw = self._gateway.get(f"league/{league_key}/teams", TEAMS_CACHE_TTL_SECONDS)
        return parse_league_teams(raw)

    def get_team_roster(self, team_key: str) -> list[RosterEntry]:
        raw = self._gateway.get(f"team/{team_key}/roster", ROSTER_CACHE_TTL_SECONDS)
        return parse_team_roster(raw)

    def get_team_roster_for_week(self, team_key: str, week: int) -> list[RosterEntry]:
        # yahoo's roster resource accepts ;week=N to return that week's actual
        # lineup, unlike get_team_roster (always "current") -- what a backtest
        # needs to reconstruct a historical matchup's real roster; same response
        # shape, so the existing parser is reused unchanged
        raw = self._gateway.get(
            f"team/{team_key}/roster;week={week}", ROSTER_HISTORICAL_CACHE_TTL_SECONDS
        )
        return parse_team_roster(raw)

    def get_standings(self, league_key: str) -> list[StandingEntry]:
        raw = self._gateway.get(f"league/{league_key}/standings", STANDINGS_CACHE_TTL_SECONDS)
        return parse_standings(raw)

    def get_scoreboard(self, league_key: str, week: int | None = None) -> list[Matchup]:
        # week=None omits the ;week= filter entirely -- yahoo then returns whatever
        # week is "current" for the league (in-season) instead of erroring, which is
        # exactly what the dashboard's live matchup view wants
        path = f"league/{league_key}/scoreboard"
        if week is not None:
            path = f"{path};week={week}"
        raw = self._gateway.get(path, SCOREBOARD_CACHE_TTL_SECONDS)
        return parse_scoreboard(raw)

    def get_draft_results(self, league_key: str) -> DraftResultsPage:
        raw = self._gateway.get(f"league/{league_key}/draftresults", DRAFT_CACHE_TTL_SECONDS)
        return parse_draft_results(raw)

    def get_league_players(self, league_key: str, status: str = "A") -> list[FreeAgentEntry]:
        """Walks the league players collection filtered by availability
        status, returning every entry across all pages.

        status="A" is yahoo's own "all available" filter (FA + waivers
        combined); ;out=ownership is what actually distinguishes the two per
        player (see parse_league_players). Yahoo exposes no total-count
        header here, so pages are walked until one comes back short of a
        full page (the last page) or empty, bounded by FREE_AGENTS_MAX_PAGES
        regardless so a misbehaving gateway can't loop forever.
        """
        entries: list[FreeAgentEntry] = []
        for page in range(FREE_AGENTS_MAX_PAGES):
            start = page * FREE_AGENTS_PAGE_SIZE
            path = (
                f"league/{league_key}/players"
                f";status={status};start={start};count={FREE_AGENTS_PAGE_SIZE};out=ownership"
            )
            raw = self._gateway.get(path, FREE_AGENTS_CACHE_TTL_SECONDS)
            page_entries = parse_league_players(raw)
            entries.extend(page_entries)
            if len(page_entries) < FREE_AGENTS_PAGE_SIZE:
                break
        return entries
