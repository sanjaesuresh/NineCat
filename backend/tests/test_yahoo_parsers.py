"""Unit tests for yahoo/parsers.py edge cases: scoreboard week_start/week_end
handling, and draft_results' pending-slot skip.

Kept separate from test_yahoo_client.py's higher-level fixture-driven tests
(which exercise the shared fixtures through the client) so these edge cases
can use small hand-built payloads instead of editing a shared fixture for
every case.
"""

import json
from datetime import date
from pathlib import Path

from ninecat.yahoo.parsers import (
    parse_draft_results,
    parse_league_metadata,
    parse_scoreboard,
    parse_standings,
    parse_user_teams,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "yahoo"


def _raw_with_matchup(matchup_overrides: dict) -> dict:
    # minimal but structurally faithful scoreboard payload: one matchup, one
    # team, teams nested under matchup's "0" wrapper (the realistic yahoo shape
    # also used by fixtures/yahoo/league_scoreboard.json)
    matchup = {
        "week": "1",
        "0": {
            "teams": {
                "0": {
                    "team": [
                        [{"team_key": "1.l.1.t.1"}, {"name": "Test Team"}],
                        {"team_stats": {"stats": [{"stat": {"stat_id": "5", "value": ".500"}}]}},
                    ]
                },
                "count": 1,
            }
        },
    }
    matchup.update(matchup_overrides)
    return {
        "fantasy_content": {
            "league": [
                {"league_key": "1.l.1"},
                {"scoreboard": [{"matchups": {"0": {"matchup": matchup}, "count": 1}}]},
            ]
        }
    }


def test_week_dates_absent_leave_fields_none_without_raising():
    # our current fixtures never carry week_start/week_end -- this is the
    # normal path today, not an error case
    raw = _raw_with_matchup({})

    matchups = parse_scoreboard(raw)

    assert matchups[0].week == 1
    assert matchups[0].week_start is None
    assert matchups[0].week_end is None


def test_week_dates_present_are_parsed():
    raw = _raw_with_matchup({"week_start": "2025-01-06", "week_end": "2025-01-12"})

    matchups = parse_scoreboard(raw)

    assert matchups[0].week_start == date(2025, 1, 6)
    assert matchups[0].week_end == date(2025, 1, 12)


def test_malformed_week_dates_degrade_to_none_without_raising():
    raw = _raw_with_matchup({"week_start": "not-a-date", "week_end": "2025-13-40"})

    matchups = parse_scoreboard(raw)

    assert matchups[0].week_start is None
    assert matchups[0].week_end is None


def _raw_draft_results(draft_result_overrides: list[dict]) -> dict:
    return {
        "fantasy_content": {
            "league": [
                {"league_key": "1.l.1", "num_teams": "2", "draft_status": "draft"},
                {
                    "draft_results": [
                        {"draft_result": dr} for dr in draft_result_overrides
                    ]
                },
            ]
        }
    }


def test_pending_slot_without_player_key_is_skipped_not_fabricated():
    # a not-yet-made pick omits player_key entirely (not null) -- it must never
    # become a DraftPick, since there is nothing to report a player_key for
    raw = _raw_draft_results(
        [
            {"pick": "1", "round": "1", "team_key": "1.l.1.t.1", "player_key": "1.p.1"},
            {"pick": "2", "round": "1", "team_key": "1.l.1.t.2"},
        ]
    )

    page = parse_draft_results(raw)

    assert len(page.results) == 1
    assert page.results[0].pick == 1
    assert page.results[0].player_key == "1.p.1"


def test_parse_user_teams_tolerates_empty_list_padding_in_team_attrs():
    # live-verified 2026-09-12: real yahoo pads absent team attributes as
    # empty LISTS interleaved with the single-key attr dicts -- the first
    # real-league sync died on exactly this (guid fetch fine, team parse not)
    raw = {
        "fantasy_content": {
            "users": {
                "0": {
                    "user": [
                        {"guid": "SANITIZEDGUID1"},
                        {
                            "games": {
                                "0": {
                                    "game": [
                                        {"game_key": "466", "code": "nba"},
                                        {
                                            "teams": {
                                                "0": {
                                                    "team": [
                                                        [
                                                            {"team_key": "466.l.12345.t.3"},
                                                            [],
                                                            {"name": "Team Alpha"},
                                                            [],
                                                        ]
                                                    ]
                                                },
                                                "count": 1,
                                            }
                                        },
                                    ]
                                },
                                "count": 1,
                            }
                        },
                    ]
                },
                "count": 1,
            }
        }
    }
    teams = parse_user_teams(raw)
    assert len(teams) == 1
    assert teams[0].team_key == "466.l.12345.t.3"
    assert teams[0].league_key == "466.l.12345"


def test_parse_standings_treats_preseason_empty_rank_as_zero():
    # live-verified 2026-09-12: before any games, yahoo sends rank as ""
    # (and percentage as "") -- 0 means "unranked yet", not a parse failure
    raw = {
        "fantasy_content": {
            "league": [
                {"league_key": "466.l.12345"},
                {
                    "standings": [
                        {
                            "teams": {
                                "0": {
                                    "team": [
                                        [
                                            {"team_key": "466.l.12345.t.3"},
                                            [],
                                            {"name": "Team Alpha"},
                                        ],
                                        {
                                            "team_standings": {
                                                "rank": "",
                                                "outcome_totals": {
                                                    "wins": 0,
                                                    "losses": 0,
                                                    "ties": 0,
                                                    "percentage": "",
                                                },
                                            }
                                        },
                                    ]
                                },
                                "count": 1,
                            }
                        }
                    ]
                },
            ]
        }
    }
    entries = parse_standings(raw)
    assert len(entries) == 1
    assert entries[0].rank == 0
    assert entries[0].wins == 0


def test_parse_standings_preseason_fixture_pins_real_rank_zero_shape():
    # league_standings_preseason.json is the live-recorded, sanitized capture
    # this hand-built test above was modeled on -- load it through the real
    # parser path (not an inline dict) so the pinned shape can't silently drift
    raw = json.loads((FIXTURE_DIR / "league_standings_preseason.json").read_text())

    entries = parse_standings(raw)

    assert len(entries) == 1
    assert entries[0].team_key == "478.l.11111.t.1"
    assert entries[0].name == "Team Alpha"
    assert entries[0].rank == 0
    assert entries[0].wins == 0
    assert entries[0].losses == 0
    assert entries[0].ties == 0


def test_parse_league_metadata_reads_the_merged_league_header():
    # league/{key} responses (and every league sub-resource) carry the merged
    # metadata dict at league[0]; historical leagues aren't listed by the
    # current-game user_leagues call, so backfill fetches this directly
    raw = {
        "fantasy_content": {
            "league": [
                {
                    "league_key": "466.l.99999",
                    "name": "Old League",
                    "season": "2025",
                    "scoring_type": "head",
                    "num_teams": 10,
                    "end_week": "19",
                }
            ]
        }
    }
    info = parse_league_metadata(raw)
    assert info.league_key == "466.l.99999"
    assert info.name == "Old League"
    assert info.season == "2025"
    assert info.scoring_type == "head"
    assert info.num_teams == 10
    # end_week bounds the backfill walk -- yahoo answers an out-of-range week
    # with no scoreboard section at all (live-verified), so walking blind past
    # the end raises instead of returning empty
    assert info.end_week == 19


def test_parse_league_metadata_tolerates_missing_end_week():
    raw = {
        "fantasy_content": {
            "league": [
                {
                    "league_key": "466.l.99999",
                    "name": "Old League",
                    "season": "2025",
                    "scoring_type": "head",
                    "num_teams": 10,
                }
            ]
        }
    }
    assert parse_league_metadata(raw).end_week is None
