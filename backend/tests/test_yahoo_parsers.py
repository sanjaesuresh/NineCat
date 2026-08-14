"""Unit tests for yahoo/parsers.py's scoreboard week_start/week_end handling.

Kept separate from test_yahoo_client.py's higher-level get_scoreboard tests
(which exercise the shared fixture through the client) so the absent/malformed
edge cases can use small hand-built payloads instead of editing the shared
fixture for every case.
"""

from datetime import date

from ninecat.yahoo.parsers import parse_scoreboard


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
