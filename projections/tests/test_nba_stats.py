"""Tests for nineproj.utils.cache, nineproj.data.nba_stats, nineproj.data.universe."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from nineproj.config import load_settings
from nineproj.data.nba_stats import SeasonLine, fetch_season_averages, provenance
from nineproj.data.universe import PlayerRecord, add_players, build_universe
from nineproj.utils import cache as cache_module
from nineproj.utils.cache import cached_fetch

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "leaguedash_2025_26_sample.json"
SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"

# CommonTeamRoster-shaped stubs for the two teams in the fixture (ATL, BOS).
# Test Bench D (9000004) is deliberately left off the ATL roster to exercise
# the "missing individual entry" null-tolerance path (not a whole-team failure).
_ROSTER_HEADERS = [
    "TeamID", "SEASON", "LeagueID", "PLAYER", "PLAYER_SLUG", "NUM", "POSITION",
    "HEIGHT", "WEIGHT", "BIRTH_DATE", "AGE", "EXP", "SCHOOL", "PLAYER_ID",
]
_ROSTERS: dict[int, dict[str, Any]] = {
    1610612737: {
        "resultSets": [
            {
                "name": "CommonTeamRoster",
                "headers": _ROSTER_HEADERS,
                "rowSet": [
                    [1610612737, "2025-26", "00", "Test Guard A", "test-guard-a", "5", "Guard",
                     "6-3", "195", "1999-01-01", "24", "3", "Test University", 9000001],
                    [1610612737, "2025-26", "00", "Test DNP E", "test-dnp-e", "9", "Center",
                     "6-11", "255", "1990-05-05", "35", "12", "Test College", 9000005],
                ],
            }
        ]
    },
    1610612738: {
        "resultSets": [
            {
                "name": "CommonTeamRoster",
                "headers": _ROSTER_HEADERS,
                "rowSet": [
                    [1610612738, "2025-26", "00", "Test Forward B", "test-forward-b", "22", "Forward",
                     "6-8", "220", "1997-02-02", "27", "5", "Test State", 9000002],
                    [1610612738, "2025-26", "00", "Test Center C", "test-center-c", "34", "Center",
                     "6-11", "250", "1994-03-03", "30", "8", "Test Tech", 9000003],
                ],
            }
        ]
    },
}


def _fixture_stats_fetcher(season: str) -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


def _fixture_roster_fetcher(season: str, team_id: int) -> dict[str, Any]:
    return _ROSTERS[team_id]


# ---------------------------------------------------------------------------
# fetch_season_averages: fixture parsing
# ---------------------------------------------------------------------------


def test_fetch_season_averages_parses_known_player_exact_values() -> None:
    lines = fetch_season_averages(
        "2025-26", fetcher=_fixture_stats_fetcher, roster_fetcher=_fixture_roster_fetcher
    )
    guard_a = next(line for line in lines if line.player_id == 9000001)

    assert guard_a == SeasonLine(
        season="2025-26",
        player_id=9000001,
        name="Test Guard A",
        team="ATL",
        position="Guard",
        age=24.0,
        games=70,
        minutes=32.5,
        fgm=6.2,
        fga=13.1,
        ftm=3.0,
        fta=3.5,
        tpm=2.1,
        pts=17.5,
        reb=3.5,
        ast=5.0,
        stl=1.3,
        blk=0.2,
        tov=2.2,
    )


def test_fetch_season_averages_returns_all_fixture_rows() -> None:
    lines = fetch_season_averages(
        "2025-26", fetcher=_fixture_stats_fetcher, roster_fetcher=_fixture_roster_fetcher
    )
    assert {line.player_id for line in lines} == {9000001, 9000002, 9000003, 9000004, 9000005}


def test_fetch_season_averages_position_null_when_missing_from_roster() -> None:
    # Test Bench D (9000004) is on the ATL roster response but not listed in
    # its rowSet -- must fall back to None rather than raising a KeyError.
    lines = fetch_season_averages(
        "2025-26", fetcher=_fixture_stats_fetcher, roster_fetcher=_fixture_roster_fetcher
    )
    bench_d = next(line for line in lines if line.player_id == 9000004)
    assert bench_d.position is None


def test_fetch_season_averages_position_null_when_roster_fetch_raises() -> None:
    def _flaky_roster_fetcher(season: str, team_id: int) -> dict[str, Any]:
        if team_id == 1610612738:  # BOS roster endpoint is down this run
            raise RuntimeError("roster endpoint unavailable")
        return _ROSTERS[team_id]

    lines = fetch_season_averages(
        "2025-26", fetcher=_fixture_stats_fetcher, roster_fetcher=_flaky_roster_fetcher
    )
    by_id = {line.player_id: line for line in lines}

    # ATL (working roster fetch) still resolves positions...
    assert by_id[9000001].position == "Guard"
    # ...while BOS (raising roster fetch) degrades to null instead of failing the whole fetch
    assert by_id[9000002].position is None
    assert by_id[9000003].position is None


def test_fetch_season_averages_live_path_threads_ttl_hours_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # H3: the live (fetcher=None) default path must actually use the
    # ttl_hours passed in from a real Settings object, not a hardcoded
    # module constant that ignores settings.cache.ttl_hours entirely
    recorded: dict[str, float] = {}

    def _recording_cached_fetch(key, ttl_hours, fetch_fn, **kwargs):
        recorded["ttl_hours"] = ttl_hours
        return json.loads(FIXTURE_PATH.read_text())

    monkeypatch.setattr(cache_module, "cached_fetch", _recording_cached_fetch)

    settings = load_settings(SHIPPED_SETTINGS)
    # roster_fetcher stays fixture-backed so only the stats-side default
    # fetcher (the one under test) goes through the recording cached_fetch
    fetch_season_averages(
        "2025-26", roster_fetcher=_fixture_roster_fetcher, ttl_hours=settings.cache.ttl_hours
    )

    assert recorded["ttl_hours"] == settings.cache.ttl_hours


def test_provenance_records_each_fetch() -> None:
    fetch_season_averages(
        "2025-26", fetcher=_fixture_stats_fetcher, roster_fetcher=_fixture_roster_fetcher
    )
    entries = provenance()
    assert any(
        entry["source"] == "NBA Stats (stats.nba.com via nba_api)"
        and entry["endpoint"] == "leaguedashplayerstats"
        and entry["season"] == "2025-26"
        for entry in entries
    )


def test_provenance_retrieved_is_todays_iso_date() -> None:
    fetch_season_averages(
        "2025-26", fetcher=_fixture_stats_fetcher, roster_fetcher=_fixture_roster_fetcher
    )
    entries = provenance()
    assert any(entry["retrieved"] == date.today().isoformat() for entry in entries)


# ---------------------------------------------------------------------------
# cached_fetch: round-trip, staleness, and hard-failure paths
# ---------------------------------------------------------------------------


def _no_sleep(_seconds: float) -> None:
    # cache tests must never actually wait out the real backoff/throttle delays
    pass


def test_cached_fetch_round_trip_second_call_does_not_refetch(tmp_path: Path) -> None:
    calls = {"count": 0}

    def _counting_fetch() -> dict[str, str]:
        calls["count"] += 1
        return {"value": "fetched"}

    first = cached_fetch("some_key", 24, _counting_fetch, cache_dir=tmp_path, sleep=_no_sleep)
    second = cached_fetch("some_key", 24, _counting_fetch, cache_dir=tmp_path, sleep=_no_sleep)

    assert first == {"value": "fetched"}
    assert second == {"value": "fetched"}
    assert calls["count"] == 1


def test_cached_fetch_serves_stale_cache_when_live_fetch_fails(tmp_path: Path) -> None:
    def _working_fetch() -> dict[str, str]:
        return {"value": "original"}

    def _raising_fetch() -> dict[str, str]:
        raise RuntimeError("network unreachable")

    cached_fetch("flaky_key", 24, _working_fetch, cache_dir=tmp_path, sleep=_no_sleep)

    stale_flag = {"triggered": False}
    result = cached_fetch(
        "flaky_key",
        0,  # ttl_hours=0 -> immediately expired, forces the refetch path
        _raising_fetch,
        cache_dir=tmp_path,
        sleep=_no_sleep,
        on_stale=lambda: stale_flag.__setitem__("triggered", True),
    )

    assert result == {"value": "original"}
    assert stale_flag["triggered"] is True


def test_cached_fetch_raises_when_no_cache_and_fetch_fails(tmp_path: Path) -> None:
    calls = {"count": 0}

    def _raising_fetch() -> dict[str, str]:
        calls["count"] += 1
        raise RuntimeError("network unreachable")

    with pytest.raises(RuntimeError, match="network unreachable"):
        cached_fetch("never_cached_key", 24, _raising_fetch, cache_dir=tmp_path, sleep=_no_sleep)

    # a permanently-failing fetch_fn must be retried up to _MAX_ATTEMPTS (3) and no more
    assert calls["count"] == 3


def test_cached_fetch_retries_then_succeeds_with_exponential_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # reset the module-level throttle clock so an earlier test's live call
    # (possibly milliseconds ago in the same process) can't inject a spurious
    # throttle sleep before this test's first attempt
    monkeypatch.setattr(cache_module, "_last_live_call_at", 0.0)

    calls = {"count": 0}
    sleep_calls: list[float] = []

    def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def _flaky_then_ok_fetch() -> dict[str, str]:
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("transient failure")
        return {"value": "ok on third try"}

    result = cached_fetch(
        "retry_key", 24, _flaky_then_ok_fetch, cache_dir=tmp_path, sleep=_record_sleep
    )

    assert result == {"value": "ok on third try"}
    assert calls["count"] == 3
    # sleep is also used for the 600ms inter-call throttle, so isolate the
    # backoff-sized waits (>= 1s) from any sub-second throttle waits mixed in
    backoff_sleeps = [seconds for seconds in sleep_calls if seconds >= 1.0]
    assert backoff_sleeps == [2.0, 4.0]


# ---------------------------------------------------------------------------
# cached_fetch: serve_expired (H2, --offline mode)
# ---------------------------------------------------------------------------


def test_serve_expired_returns_stale_cache_without_calling_fetcher_or_sleeping(tmp_path: Path) -> None:
    def _working_fetch() -> dict[str, str]:
        return {"value": "original"}

    cached_fetch("expired_key", 24, _working_fetch, cache_dir=tmp_path, sleep=_no_sleep)

    sleep_calls: list[float] = []

    def _raising_fetch() -> dict[str, str]:
        raise RuntimeError("offline mode: live fetch forbidden")

    result = cached_fetch(
        "expired_key",
        0,  # ttl_hours=0 -> immediately expired
        _raising_fetch,
        cache_dir=tmp_path,
        sleep=sleep_calls.append,
        serve_expired=True,
    )

    assert result == {"value": "original"}
    assert sleep_calls == []


def test_serve_expired_logs_a_warning_naming_the_key_and_fetched_at(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def _working_fetch() -> dict[str, str]:
        return {"value": "original"}

    cached_fetch("warn_key", 24, _working_fetch, cache_dir=tmp_path, sleep=_no_sleep)

    def _must_not_be_called() -> dict[str, str]:
        raise AssertionError("serve_expired must never call fetch_fn when a cache file exists")

    with caplog.at_level(logging.WARNING, logger="nineproj.utils.cache"):
        cached_fetch(
            "warn_key",
            0,  # immediately expired
            _must_not_be_called,
            cache_dir=tmp_path,
            sleep=_no_sleep,
            serve_expired=True,
        )

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "warn_key" in message
    assert "T" in message  # the ISO fetched_at timestamp (YYYY-MM-DDTHH:MM:SS...) is present


def test_serve_expired_with_no_cache_calls_fetcher_once_no_retries(tmp_path: Path) -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []

    def _fetch() -> dict[str, str]:
        calls["count"] += 1
        return {"value": "fetched"}

    result = cached_fetch(
        "never_cached_key",
        24,
        _fetch,
        cache_dir=tmp_path,
        sleep=sleep_calls.append,
        serve_expired=True,
    )

    assert result == {"value": "fetched"}
    assert calls["count"] == 1
    assert sleep_calls == []


# ---------------------------------------------------------------------------
# build_universe / add_players
# ---------------------------------------------------------------------------


def _season_line(season: str, player_id: int, minutes: float, position: str | None = "Guard") -> SeasonLine:
    return SeasonLine(
        season=season,
        player_id=player_id,
        name=f"Player {player_id}",
        team="ATL",
        position=position,
        age=25.0,
        games=50,
        minutes=minutes,
        fgm=5.0,
        fga=10.0,
        ftm=2.0,
        fta=2.5,
        tpm=1.0,
        pts=13.0,
        reb=4.0,
        ast=3.0,
        stl=1.0,
        blk=0.5,
        tov=1.5,
    )


def test_build_universe_includes_current_season_player_with_minutes() -> None:
    lines_by_season = {
        "2025-26": [_season_line("2025-26", 1, minutes=30.0, position="Guard")],
        "2024-25": [_season_line("2024-25", 1, minutes=28.0, position="Guard")],
    }
    records = build_universe(lines_by_season)

    assert len(records) == 1
    record = records[0]
    assert record.player_id == 1
    assert record.slot_classes == frozenset({"PG", "SG", "G", "UTIL"})
    assert record.seasons_available == ["2024-25", "2025-26"]


def test_build_universe_includes_returner_only_present_in_older_season() -> None:
    # B1: player 2 sat out 2025-26 entirely (a returner gap, e.g. season-long
    # injury) but has real 2024-25 minutes -- must still enter the pool, with
    # team/age read off that most-recent-with-minutes (2024-25) line
    lines_by_season = {
        "2025-26": [_season_line("2025-26", 1, minutes=30.0)],
        "2024-25": [
            _season_line("2024-25", 1, minutes=28.0),
            _season_line("2024-25", 2, minutes=20.0),
        ],
    }
    records = build_universe(lines_by_season)
    by_id = {record.player_id: record for record in records}

    assert set(by_id) == {1, 2}
    assert by_id[2].team == "ATL"  # _season_line's fixed team, off the 2024-25 line
    assert by_id[2].age == pytest.approx(26.0)  # fixture age 25.0 + 1 season back
    assert by_id[2].seasons_available == ["2024-25"]


def test_build_universe_team_and_age_come_from_most_recent_line_with_minutes() -> None:
    # player 3 has zero minutes (DNP) in 2025-26 -- excluded from that season's
    # count -- but real 2024-25 minutes; team must be the 2024-25 value, not a
    # stale earlier-still line, since 2024-25 is their most recent real one.
    # Age is extrapolated by the season offset (2024-25 is one season back
    # of the two season keys present here -> +1): raw 27.0 -> 28.0.
    older_line = replace(_season_line("2024-25", 3, minutes=25.0), team="BOS", age=27.0)
    lines_by_season = {
        "2025-26": [_season_line("2025-26", 3, minutes=0.0)],
        "2024-25": [older_line],
    }
    records = build_universe(lines_by_season)
    record = next(r for r in records if r.player_id == 3)

    assert record.team == "BOS"
    assert record.age == pytest.approx(28.0)
    assert record.seasons_available == ["2024-25"]


def test_build_universe_returner_age_extrapolated_by_season_offset() -> None:
    # coordinator follow-up: a returner's recorded age is stale by however
    # many seasons they're missing from the top -- extrapolate it forward by
    # the season offset so it lands on the same reference season (the newest
    # one present) a current player's raw age already is
    one_back = replace(_season_line("2024-25", 10, minutes=30.0), age=34.0)
    two_back = replace(_season_line("2023-24", 11, minutes=28.0), age=34.0)
    lines_by_season = {
        "2025-26": [],
        "2024-25": [one_back],
        "2023-24": [two_back],
    }
    records = build_universe(lines_by_season)
    by_id = {record.player_id: record for record in records}

    # 2024-25 is index 1 of the 3 season keys present (2025-26, 2024-25,
    # 2023-24) -- one season back -> +1
    assert by_id[10].age == pytest.approx(35.0)
    # 2023-24 is index 2 -- two seasons back -> +2
    assert by_id[11].age == pytest.approx(36.0)


def test_build_universe_excludes_zero_minute_current_season_player() -> None:
    lines_by_season = {
        "2025-26": [
            _season_line("2025-26", 1, minutes=30.0),
            _season_line("2025-26", 2, minutes=0.0),
        ],
    }
    records = build_universe(lines_by_season)

    assert {record.player_id for record in records} == {1}


def test_build_universe_empty_input_returns_empty_list() -> None:
    assert build_universe({}) == []


def test_build_universe_none_position_maps_to_util_only_slot_class() -> None:
    lines_by_season = {
        "2025-26": [_season_line("2025-26", 1, minutes=20.0, position=None)],
    }
    records = build_universe(lines_by_season)

    assert records[0].position is None
    assert records[0].slot_classes == frozenset({"UTIL"})


def test_add_players_dedupes_by_player_id() -> None:
    existing = [
        PlayerRecord(
            player_id=1,
            name="Existing Player",
            team="ATL",
            position="Guard",
            slot_classes=frozenset({"PG", "G", "UTIL"}),
            age=25.0,
            seasons_available=["2025-26"],
        )
    ]
    extra = [
        PlayerRecord(
            player_id=1,  # duplicate -- must not be appended again
            name="Existing Player (dup)",
            team="ATL",
            position="Guard",
            slot_classes=frozenset({"PG", "G", "UTIL"}),
            age=25.0,
            seasons_available=["2025-26"],
        ),
        PlayerRecord(
            player_id=2,
            name="New Rookie",
            team="BOS",
            position=None,
            slot_classes=frozenset({"UTIL"}),
            age=19.0,
            seasons_available=[],
        ),
    ]

    merged = add_players(existing, extra)

    assert [record.player_id for record in merged] == [1, 2]
    assert merged[0].name == "Existing Player"  # original entry, not the duplicate's
