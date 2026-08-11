"""Unwraps Yahoo Fantasy API's ?format=json response shapes into plain dataclasses.

Yahoo's JSON is deeply and inconsistently nested: some collections (users, games,
leagues, teams, players, matchups, roster positions, stat categories) arrive as
EITHER a plain JSON array OR a dict of numeric-string keys plus a "count" key
({"0": {...}, "1": {...}, "count": N}), depending on endpoint/version; some
single sub-resources (settings, standings, roster, scoreboard, a matchup's teams)
arrive wrapped under a "0" key alongside sibling scalar metadata (week,
coverage_type, ...), or unwrapped as a bare list/plain dict; team/player
attributes arrive as a list of many single-key dicts that must be merged, while
league/game attributes arrive already merged into one dict. All of that
unwrapping is owned here so client.py can stay a thin path-compose-and-call layer.
"""

from __future__ import annotations

from dataclasses import dataclass


class YahooParseError(ValueError):
    """Raised when a parser can't find or coerce an expected value in Yahoo's response.

    Carries the dotted key path so a broken/changed Yahoo response (or a bad
    fixture) points at exactly what's missing or malformed, instead of a bare
    KeyError/ValueError with no context about where in the nested structure it
    happened.
    """

    def __init__(self, key_path: str):
        super().__init__(f"Yahoo response missing or malformed expected key path: {key_path}")
        self.key_path = key_path


# --- dataclasses (Task 8/10/13 build against these fields) ---


@dataclass(frozen=True)
class LeagueInfo:
    league_key: str
    name: str
    season: str
    scoring_type: str
    num_teams: int


@dataclass(frozen=True)
class CategoryInfo:
    stat_id: int
    name: str
    display_name: str
    is_negative: bool


@dataclass(frozen=True)
class RosterPosition:
    position: str
    count: int


@dataclass(frozen=True)
class LeagueSettings:
    categories: list[CategoryInfo]
    roster_positions: list[RosterPosition]
    max_weekly_adds: int | None
    playoff_start_week: int | None
    num_playoff_teams: int | None


@dataclass(frozen=True)
class TeamInfo:
    team_key: str
    name: str
    logo_url: str | None
    manager_name: str | None


@dataclass(frozen=True)
class RosterEntry:
    player_key: str
    name: str
    eligible_positions: list[str]
    selected_position: str
    injury_status: str | None
    nba_team_abbr: str


@dataclass(frozen=True)
class StandingEntry:
    team_key: str
    name: str
    rank: int
    wins: int
    losses: int
    ties: int


@dataclass(frozen=True)
class MatchupTeam:
    team_key: str
    name: str
    # keyed by stat_id as int, matching CategoryInfo.stat_id, so callers can
    # cross-reference a category's settings and its matchup total without a cast
    category_totals: dict[int, str]


@dataclass(frozen=True)
class Matchup:
    week: int
    teams: list[MatchupTeam]


# --- shared unwrapping helpers ---


def _get(d: dict, key: str, path: str):
    """Dict lookup that raises YahooParseError (with the full path) instead of KeyError."""
    if not isinstance(d, dict) or key not in d:
        raise YahooParseError(f"{path}.{key}")
    return d[key]


def _get_int(value, path: str) -> int:
    """int() that raises YahooParseError (with path) instead of a bare ValueError/TypeError."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise YahooParseError(path) from exc


def _get_optional_int(value, path: str) -> int | None:
    # yahoo represents an unset numeric league setting as "" or "-1" rather than
    # omitting the key or using null, so both sentinels map to None here; strip
    # first so stray whitespace (" -1 ") doesn't slip past the sentinel check
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized == "" or normalized == "-1":
        return None
    return _get_int(normalized, path)


def _collection_items(d, path: str) -> list:
    # yahoo represents array-like collections two different ways depending on
    # endpoint/version: a plain JSON array, or a dict of numeric-string keys plus
    # a "count" key ({"0": {...}, "1": {...}, "count": N}); tolerate both so a
    # parse site never has to know or guess which one it's looking at
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        count = _get_int(_get(d, "count", path), f"{path}.count")
        return [_get(d, str(i), path) for i in range(count)]
    raise YahooParseError(path)


def _find_section(items, key: str, path: str) -> dict:
    # a "list" node (e.g. user, game, team) mixes plain dicts and nested lists;
    # the sub-resource we want (games/leagues/roster/team_stats/...) is whichever
    # dict element actually carries that key, not a fixed index
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and key in item:
                return item[key]
    raise YahooParseError(f"{path}.{key}")


def _unwrap(d, path: str) -> dict:
    # a single sub-resource (settings, standings, roster, scoreboard, a
    # matchup's teams) arrives one of three ways: wrapped as {"0": {...},
    # <sibling scalar metadata>} (the common real-Yahoo case), as a bare
    # single-element list [{...}], or as a plain dict with no "0" wrapper at
    # all -- this tolerates all three and returns the inner dict to read from
    if isinstance(d, dict):
        return d.get("0", d)
    if isinstance(d, list) and d:
        return d[0]
    raise YahooParseError(path)


def _merge_attrs(items: list, path: str) -> dict:
    # team/player attributes arrive as a list of many single-key dicts (a yahoo
    # quirk distinct from league/game, which arrive pre-merged); flatten to one dict
    if not isinstance(items, list):
        raise YahooParseError(path)
    merged: dict = {}
    for item in items:
        if not isinstance(item, dict):
            raise YahooParseError(path)
        merged.update(item)
    return merged


# --- get_user_leagues ---


def parse_user_leagues(raw: dict) -> list[LeagueInfo]:
    fc = _get(raw, "fantasy_content", "fantasy_content")
    users = _get(fc, "users", "fantasy_content.users")
    leagues: list[LeagueInfo] = []

    for i, user_wrap in enumerate(_collection_items(users, "fantasy_content.users")):
        user_path = f"fantasy_content.users[{i}]"
        user = _get(user_wrap, "user", user_path)
        games_section = _find_section(user, "games", f"{user_path}.user")

        for j, game_wrap in enumerate(_collection_items(games_section, f"{user_path}.user.games")):
            game_path = f"{user_path}.user.games[{j}]"
            game = _get(game_wrap, "game", game_path)
            leagues_section = _find_section(game, "leagues", f"{game_path}.game")

            for k, league_wrap in enumerate(
                _collection_items(leagues_section, f"{game_path}.game.leagues")
            ):
                league_path = f"{game_path}.game.leagues[{k}]"
                league_list = _get(league_wrap, "league", league_path)
                attrs = league_list[0] if isinstance(league_list, list) else league_list
                attrs_path = f"{league_path}.league"
                leagues.append(
                    LeagueInfo(
                        league_key=_get(attrs, "league_key", attrs_path),
                        name=_get(attrs, "name", attrs_path),
                        season=str(_get(attrs, "season", attrs_path)),
                        scoring_type=_get(attrs, "scoring_type", attrs_path),
                        num_teams=_get_int(
                            _get(attrs, "num_teams", attrs_path), f"{attrs_path}.num_teams"
                        ),
                    )
                )

    return leagues


# --- get_league_settings ---


def parse_league_settings(raw: dict) -> LeagueSettings:
    fc = _get(raw, "fantasy_content", "fantasy_content")
    league_list = _get(fc, "league", "fantasy_content.league")
    settings_section = _find_section(league_list, "settings", "fantasy_content.league")
    path = "fantasy_content.league.settings"
    settings = _unwrap(settings_section, path)

    roster_positions_raw = _get(settings, "roster_positions", path)
    roster_positions = []
    for i, item in enumerate(
        _collection_items(roster_positions_raw, f"{path}.roster_positions")
    ):
        rp_path = f"{path}.roster_positions[{i}]"
        rp = _get(item, "roster_position", rp_path)
        roster_positions.append(
            RosterPosition(
                position=_get(rp, "position", f"{rp_path}.roster_position"),
                count=_get_int(
                    _get(rp, "count", f"{rp_path}.roster_position"),
                    f"{rp_path}.roster_position.count",
                ),
            )
        )

    stat_categories = _get(settings, "stat_categories", path)
    stats_raw = _get(stat_categories, "stats", f"{path}.stat_categories")
    categories = []
    for i, item in enumerate(_collection_items(stats_raw, f"{path}.stat_categories.stats")):
        stat_path = f"{path}.stat_categories.stats[{i}]"
        stat = _get(item, "stat", stat_path)
        # yahoo lists display-only stats (e.g. GP, FGM/A) alongside real scoring
        # categories in the same array; only the latter counts toward the 9 cats
        if str(stat.get("is_only_display_stat", "0")) == "1":
            continue
        categories.append(
            CategoryInfo(
                stat_id=_get_int(_get(stat, "stat_id", f"{stat_path}.stat"), f"{stat_path}.stat.stat_id"),
                name=_get(stat, "name", f"{stat_path}.stat"),
                display_name=_get(stat, "display_name", f"{stat_path}.stat"),
                # yahoo marks a lower-is-better category (e.g. turnovers) with
                # sort_order "0"; everything else sorts "1" (higher is better)
                is_negative=str(_get(stat, "sort_order", f"{stat_path}.stat")) == "0",
            )
        )

    return LeagueSettings(
        categories=categories,
        roster_positions=roster_positions,
        max_weekly_adds=_get_optional_int(settings.get("max_weekly_adds"), f"{path}.max_weekly_adds"),
        playoff_start_week=_get_optional_int(
            settings.get("playoff_start_week"), f"{path}.playoff_start_week"
        ),
        num_playoff_teams=_get_optional_int(
            settings.get("num_playoff_teams"), f"{path}.num_playoff_teams"
        ),
    )


# --- get_league_teams ---


def parse_league_teams(raw: dict) -> list[TeamInfo]:
    fc = _get(raw, "fantasy_content", "fantasy_content")
    league_list = _get(fc, "league", "fantasy_content.league")
    teams_section = _find_section(league_list, "teams", "fantasy_content.league")

    teams: list[TeamInfo] = []
    for i, team_wrap in enumerate(_collection_items(teams_section, "fantasy_content.league.teams")):
        team_path = f"fantasy_content.league.teams[{i}]"
        team_list = _get(team_wrap, "team", team_path)
        attrs_list = team_list[0] if isinstance(team_list, list) else team_list
        attrs = _merge_attrs(attrs_list, f"{team_path}.team")

        # team_logos/managers may themselves arrive as a plain array or a
        # numeric-key+count dict, same as any other yahoo collection
        logo_url = None
        team_logos = attrs.get("team_logos")
        if team_logos:
            logo_items = _collection_items(team_logos, f"{team_path}.team.team_logos")
            if logo_items:
                logo_url = logo_items[0].get("team_logo", {}).get("url")

        manager_name = None
        managers = attrs.get("managers")
        if managers:
            manager_items = _collection_items(managers, f"{team_path}.team.managers")
            if manager_items:
                manager_name = manager_items[0].get("manager", {}).get("nickname")

        teams.append(
            TeamInfo(
                team_key=_get(attrs, "team_key", f"{team_path}.team"),
                name=_get(attrs, "name", f"{team_path}.team"),
                logo_url=logo_url,
                manager_name=manager_name,
            )
        )

    return teams


# --- get_team_roster ---


def parse_team_roster(raw: dict) -> list[RosterEntry]:
    fc = _get(raw, "fantasy_content", "fantasy_content")
    team_list = _get(fc, "team", "fantasy_content.team")
    roster_section = _find_section(team_list, "roster", "fantasy_content.team")
    roster = _unwrap(roster_section, "fantasy_content.team.roster")
    players_section = _get(roster, "players", "fantasy_content.team.roster")

    entries: list[RosterEntry] = []
    for i, player_wrap in enumerate(
        _collection_items(players_section, "fantasy_content.team.roster.players")
    ):
        player_path = f"fantasy_content.team.roster.players[{i}]"
        player = _get(player_wrap, "player", player_path)
        attrs_list = player[0] if isinstance(player, list) else player
        attrs = _merge_attrs(attrs_list, f"{player_path}.player")

        selected_position_section = _find_section(
            player, "selected_position", f"{player_path}.player"
        )
        selected_position_attrs = _merge_attrs(
            selected_position_section, f"{player_path}.player.selected_position"
        )
        selected_position = _get(
            selected_position_attrs, "position", f"{player_path}.player.selected_position"
        )

        name_dict = _get(attrs, "name", f"{player_path}.player")
        name = _get(name_dict, "full", f"{player_path}.player.name")
        # eligible_positions is itself a collection -- may arrive as a plain
        # array or a numeric-key+count dict, same as any other yahoo collection
        eligible_positions = [
            p.get("position")
            for p in _collection_items(
                attrs.get("eligible_positions", []), f"{player_path}.player.eligible_positions"
            )
        ]

        entries.append(
            RosterEntry(
                player_key=_get(attrs, "player_key", f"{player_path}.player"),
                name=name,
                eligible_positions=eligible_positions,
                selected_position=selected_position,
                # absent "status" key means healthy -- yahoo only includes it
                # when a player has an injury designation (INJ, GTD, O, DTD, ...)
                injury_status=attrs.get("status"),
                nba_team_abbr=_get(attrs, "editorial_team_abbr", f"{player_path}.player"),
            )
        )

    return entries


# --- get_standings ---


def parse_standings(raw: dict) -> list[StandingEntry]:
    fc = _get(raw, "fantasy_content", "fantasy_content")
    league_list = _get(fc, "league", "fantasy_content.league")
    standings_section = _find_section(league_list, "standings", "fantasy_content.league")
    standings = _unwrap(standings_section, "fantasy_content.league.standings")
    teams_section = _get(standings, "teams", "fantasy_content.league.standings")

    entries: list[StandingEntry] = []
    for i, team_wrap in enumerate(
        _collection_items(teams_section, "fantasy_content.league.standings.teams")
    ):
        team_path = f"fantasy_content.league.standings.teams[{i}]"
        team_list = _get(team_wrap, "team", team_path)
        attrs_list = team_list[0] if isinstance(team_list, list) else team_list
        attrs = _merge_attrs(attrs_list, f"{team_path}.team")

        team_standings = _find_section(team_list, "team_standings", f"{team_path}.team")
        outcome = _get(team_standings, "outcome_totals", f"{team_path}.team.team_standings")
        outcome_path = f"{team_path}.team.team_standings.outcome_totals"

        entries.append(
            StandingEntry(
                team_key=_get(attrs, "team_key", f"{team_path}.team"),
                name=_get(attrs, "name", f"{team_path}.team"),
                rank=_get_int(
                    _get(team_standings, "rank", f"{team_path}.team.team_standings"),
                    f"{team_path}.team.team_standings.rank",
                ),
                wins=_get_int(_get(outcome, "wins", outcome_path), f"{outcome_path}.wins"),
                losses=_get_int(_get(outcome, "losses", outcome_path), f"{outcome_path}.losses"),
                ties=_get_int(_get(outcome, "ties", outcome_path), f"{outcome_path}.ties"),
            )
        )

    return entries


# --- get_scoreboard ---


def parse_scoreboard(raw: dict) -> list[Matchup]:
    fc = _get(raw, "fantasy_content", "fantasy_content")
    league_list = _get(fc, "league", "fantasy_content.league")
    scoreboard_section = _find_section(league_list, "scoreboard", "fantasy_content.league")
    scoreboard = _unwrap(scoreboard_section, "fantasy_content.league.scoreboard")
    matchups_section = _get(scoreboard, "matchups", "fantasy_content.league.scoreboard")

    matchups: list[Matchup] = []
    for i, matchup_wrap in enumerate(
        _collection_items(matchups_section, "fantasy_content.league.scoreboard.matchups")
    ):
        matchup_path = f"fantasy_content.league.scoreboard.matchups[{i}]"
        matchup = _get(matchup_wrap, "matchup", matchup_path)
        week = _get_int(_get(matchup, "week", f"{matchup_path}.matchup"), f"{matchup_path}.matchup.week")
        # the teams collection nests under matchup's own "0" key alongside the
        # "week" sibling in the realistic shape, but some responses give it flat
        teams_body = _unwrap(matchup, f"{matchup_path}.matchup")
        teams_section = _get(teams_body, "teams", f"{matchup_path}.matchup")

        matchup_teams: list[MatchupTeam] = []
        for j, team_wrap in enumerate(
            _collection_items(teams_section, f"{matchup_path}.matchup.teams")
        ):
            team_path = f"{matchup_path}.matchup.teams[{j}]"
            team_list = _get(team_wrap, "team", team_path)
            attrs_list = team_list[0] if isinstance(team_list, list) else team_list
            attrs = _merge_attrs(attrs_list, f"{team_path}.team")

            team_stats = _find_section(team_list, "team_stats", f"{team_path}.team")
            stats_raw = _get(team_stats, "stats", f"{team_path}.team.team_stats")
            category_totals: dict[int, str] = {}
            for k, stat_wrap in enumerate(
                _collection_items(stats_raw, f"{team_path}.team.team_stats.stats")
            ):
                stat_path = f"{team_path}.team.team_stats.stats[{k}]"
                stat = _get(stat_wrap, "stat", stat_path)
                stat_id = _get_int(_get(stat, "stat_id", f"{stat_path}.stat"), f"{stat_path}.stat.stat_id")
                value = str(_get(stat, "value", f"{stat_path}.stat"))
                category_totals[stat_id] = value

            matchup_teams.append(
                MatchupTeam(
                    team_key=_get(attrs, "team_key", f"{team_path}.team"),
                    name=_get(attrs, "name", f"{team_path}.team"),
                    category_totals=category_totals,
                )
            )

        matchups.append(Matchup(week=week, teams=matchup_teams))

    return matchups
