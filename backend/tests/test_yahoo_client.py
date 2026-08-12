import json
from pathlib import Path

import pytest

from ninecat.yahoo.client import (
    LEAGUES_CACHE_TTL_SECONDS,
    ROSTER_CACHE_TTL_SECONDS,
    SCOREBOARD_CACHE_TTL_SECONDS,
    SETTINGS_CACHE_TTL_SECONDS,
    STANDINGS_CACHE_TTL_SECONDS,
    TEAMS_CACHE_TTL_SECONDS,
    YahooClient,
)
from ninecat.yahoo.parsers import YahooParseError, parse_league_settings

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "yahoo"

LEAGUE_KEY = "466.l.12345"
TEAM_KEY = "466.l.12345.t.1"
WEEK = 3


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


class _StubGateway:
    """Stands in for YahooGateway: returns canned fixture JSON keyed by exact
    resource path, and records (path, ttl) calls so tests can assert the
    client composed the right path and used the right cache TTL."""

    def __init__(self, responses: dict[str, dict]):
        self._responses = responses
        self.calls: list[tuple[str, int]] = []

    def get(self, resource_path: str, cache_ttl_seconds: int) -> dict:
        self.calls.append((resource_path, cache_ttl_seconds))
        return self._responses[resource_path]


# --- get_user_leagues ---


def test_get_user_leagues_parses_two_leagues_with_season_and_scoring_type():
    gateway = _StubGateway(
        {"users;use_login=1/games;game_keys=nba/leagues": _load("user_leagues.json")}
    )
    client = YahooClient(gateway)

    leagues = client.get_user_leagues()

    assert len(leagues) == 2
    assert leagues[0].league_key == "466.l.12345"
    assert leagues[0].name == "Nine Cat Nation"
    assert leagues[0].season == "2024"
    assert leagues[0].scoring_type == "head"
    assert leagues[0].num_teams == 10
    assert leagues[1].league_key == "454.l.67890"
    assert leagues[1].season == "2023"
    assert gateway.calls == [
        ("users;use_login=1/games;game_keys=nba/leagues", LEAGUES_CACHE_TTL_SECONDS)
    ]


# --- get_league_settings ---


def test_get_league_settings_parses_nine_categories_to_flagged_negative_and_positions():
    gateway = _StubGateway({f"league/{LEAGUE_KEY}/settings": _load("league_settings.json")})
    client = YahooClient(gateway)

    settings = client.get_league_settings(LEAGUE_KEY)

    # is_only_display_stat categories (GP, FGM/A) must be filtered out
    assert len(settings.categories) == 9
    stat_ids = {c.stat_id for c in settings.categories}
    assert stat_ids == {5, 8, 10, 12, 15, 16, 17, 18, 19}

    to_category = next(c for c in settings.categories if c.stat_id == 19)
    assert to_category.is_negative is True
    assert to_category.display_name == "TO"
    pts_category = next(c for c in settings.categories if c.stat_id == 12)
    assert pts_category.is_negative is False

    assert settings.max_weekly_adds == 4
    assert settings.playoff_start_week == 20
    assert settings.num_playoff_teams == 4

    assert len(settings.roster_positions) == 10
    bench = next(rp for rp in settings.roster_positions if rp.position == "BN")
    assert bench.count == 3
    assert gateway.calls == [(f"league/{LEAGUE_KEY}/settings", SETTINGS_CACHE_TTL_SECONDS)]


# --- get_league_teams ---


def test_get_league_teams_parses_teams_with_one_missing_logo():
    gateway = _StubGateway({f"league/{LEAGUE_KEY}/teams": _load("league_teams.json")})
    client = YahooClient(gateway)

    teams = client.get_league_teams(LEAGUE_KEY)

    assert len(teams) == 2
    assert teams[0].team_key == "466.l.12345.t.1"
    assert teams[0].name == "Air Bud"
    assert teams[0].logo_url == "https://s.yimg.com/logos/airbud.png"
    assert teams[0].manager_name == "Sanjae"
    # second team's fixture has no team_logos key at all
    assert teams[1].logo_url is None
    assert teams[1].manager_name == "Jordan"
    assert gateway.calls == [(f"league/{LEAGUE_KEY}/teams", TEAMS_CACHE_TTL_SECONDS)]


# --- get_team_roster ---


def test_get_team_roster_parses_injured_and_healthy_players():
    gateway = _StubGateway({f"team/{TEAM_KEY}/roster": _load("team_roster.json")})
    client = YahooClient(gateway)

    roster = client.get_team_roster(TEAM_KEY)

    assert len(roster) == 2
    # lebron's eligible_positions is a plain array in the fixture
    lebron = next(r for r in roster if r.player_key == "466.p.5583")
    assert lebron.name == "LeBron James"
    assert lebron.eligible_positions == ["SF", "PF"]
    assert lebron.selected_position == "SF"
    assert lebron.injury_status == "INJ"
    assert lebron.nba_team_abbr == "LAL"

    # jokic's eligible_positions is a numeric-key+count dict in the fixture --
    # exercises the _collection_items dict branch for this field specifically
    jokic = next(r for r in roster if r.player_key == "466.p.4612")
    assert jokic.injury_status is None
    assert jokic.eligible_positions == ["C"]
    assert gateway.calls == [(f"team/{TEAM_KEY}/roster", ROSTER_CACHE_TTL_SECONDS)]


# --- get_standings ---


def test_get_standings_preserves_order_and_returns_ints():
    gateway = _StubGateway({f"league/{LEAGUE_KEY}/standings": _load("league_standings.json")})
    client = YahooClient(gateway)

    standings = client.get_standings(LEAGUE_KEY)

    assert len(standings) == 2
    # fixture lists Rebound City (rank 1) before Air Bud (rank 2) -- order must
    # be preserved rather than re-sorted by the parser
    assert [s.name for s in standings] == ["Rebound City", "Air Bud"]
    assert standings[0].rank == 1
    assert standings[0].wins == 12
    assert standings[0].losses == 3
    assert standings[0].ties == 1
    assert isinstance(standings[0].wins, int)
    assert gateway.calls == [(f"league/{LEAGUE_KEY}/standings", STANDINGS_CACHE_TTL_SECONDS)]


# --- get_scoreboard ---


def test_get_scoreboard_parses_two_matchups_with_category_totals_keyed_by_stat_id():
    gateway = _StubGateway(
        {f"league/{LEAGUE_KEY}/scoreboard;week={WEEK}": _load("league_scoreboard.json")}
    )
    client = YahooClient(gateway)

    matchups = client.get_scoreboard(LEAGUE_KEY, WEEK)

    assert len(matchups) == 2

    # matchup 0's fixture nests "teams" under a "0" wrapper alongside "week"
    # (the realistic yahoo shape), and its second team's team_stats.stats is a
    # numeric-key+count dict rather than a plain array
    first = matchups[0]
    assert first.week == 3
    assert len(first.teams) == 2
    assert first.teams[0].team_key == "466.l.12345.t.1"
    # keys are int, matching CategoryInfo.stat_id
    assert first.teams[0].category_totals[12] == "301"
    assert first.teams[0].category_totals[19] == "38"
    assert first.teams[1].name == "Rebound City"
    assert first.teams[1].category_totals[5] == ".501"

    # matchup 1's fixture gives "teams" flat (no "0" wrapper) as a plain array --
    # the tolerant fallback path, exercised separately from matchup 0's wrapped form
    second = matchups[1]
    assert second.week == 3
    assert [t.name for t in second.teams] == ["Splash Zone", "Paint Patrol"]
    assert second.teams[0].category_totals[19] == "41"

    assert gateway.calls == [
        (f"league/{LEAGUE_KEY}/scoreboard;week={WEEK}", SCOREBOARD_CACHE_TTL_SECONDS)
    ]


def test_get_scoreboard_without_week_omits_week_param_and_uses_response_week():
    gateway = _StubGateway(
        {f"league/{LEAGUE_KEY}/scoreboard": _load("league_scoreboard_current_week.json")}
    )
    client = YahooClient(gateway)

    matchups = client.get_scoreboard(LEAGUE_KEY)

    assert len(matchups) == 1
    assert matchups[0].week == 5
    assert [t.name for t in matchups[0].teams] == ["Air Bud", "Rebound City"]
    assert gateway.calls == [(f"league/{LEAGUE_KEY}/scoreboard", SCOREBOARD_CACHE_TTL_SECONDS)]


# --- get_user_teams ---


def test_get_user_teams_derives_league_key_from_team_key_prefix():
    gateway = _StubGateway(
        {"users;use_login=1/games;game_keys=nba/teams": _load("user_teams.json")}
    )
    client = YahooClient(gateway)

    teams = client.get_user_teams()

    assert len(teams) == 2
    # first game's teams arrive as a numeric-key+count dict in the fixture
    assert teams[0].team_key == "466.l.12345.t.1"
    assert teams[0].league_key == "466.l.12345"
    # second game's teams arrive as a plain array -- exercises the other branch
    assert teams[1].team_key == "454.l.67890.t.7"
    assert teams[1].league_key == "454.l.67890"
    assert gateway.calls == [
        ("users;use_login=1/games;game_keys=nba/teams", TEAMS_CACHE_TTL_SECONDS)
    ]


# --- malformed fixture -> clear YahooParseError, not a bare KeyError ---


def test_parse_league_settings_raises_clear_error_on_missing_stat_categories():
    raw = _load("malformed_league_settings.json")

    with pytest.raises(YahooParseError) as exc_info:
        parse_league_settings(raw)

    # the error must name the missing key path, not just be a bare KeyError
    assert "stat_categories" in str(exc_info.value)


# --- unset optional numeric settings ("" / "-1" sentinels) -> None ---


def test_parse_league_settings_treats_empty_string_and_negative_one_as_unset():
    # yahoo represents an unset numeric league setting as "" or "-1" rather than
    # omitting the key entirely or using null; both must coerce to None, not raise
    raw = {
        "fantasy_content": {
            "league": [
                {"league_key": "466.l.99999"},
                {
                    "settings": [
                        {
                            "max_weekly_adds": "-1",
                            "playoff_start_week": "",
                            # num_playoff_teams omitted entirely -- also None
                            "roster_positions": [],
                            "stat_categories": {"stats": []},
                        }
                    ]
                },
            ]
        }
    }

    settings = parse_league_settings(raw)

    assert settings.max_weekly_adds is None
    assert settings.playoff_start_week is None
    assert settings.num_playoff_teams is None
    assert settings.categories == []
    assert settings.roster_positions == []
