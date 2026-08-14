"""Tests for nineproj.export.pipeline/dataset/validate (Task 14)."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from typing import Any

import pytest

from nineproj.config import load_settings
from nineproj.data.nba_stats import SeasonLine, fetch_season_averages
from nineproj.data.schedule import ScheduleRow, fetch_schedule
from nineproj.export.dataset import build_dataset
from nineproj.export.pipeline import run_pipeline
from nineproj.export.validate import validate_dataset
from nineproj.research.schema import SourceRef, TransactionEvent
from nineproj.research.store import EvidenceStore, load_store

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"
LEAGUEDASH_FIXTURE = FIXTURES / "leaguedash_2025_26_sample.json"
SCHEDULE_FIXTURE = FIXTURES / "schedule_2026_27_sample.json"
RESEARCH_DIR = FIXTURES / "research"

_CSV_HEADER = (
    "player", "team", "games", "fgm", "fga", "ftm", "fta", "tpm", "pts",
    "reb", "ast", "stl", "blk", "tov",
)

_PLAYER_BLOCKS = (
    "rank", "player_id", "name", "team", "positions", "age",
    "projection", "fantasy", "availability", "role", "schedule",
    "consensus", "model", "analysis", "sources",
)


def _stats_fetcher(season: str) -> dict[str, Any]:
    return json.loads(LEAGUEDASH_FIXTURE.read_text())


def _roster_fetcher(season: str, team_id: int) -> dict[str, Any]:
    # positions aren't exercised by this integration test -- an empty roster
    # leaves every player positionless (slot_classes -> UTIL-only), which is
    # still a valid "positions" block to assert against
    return {
        "resultSets": [
            {"name": "CommonTeamRoster", "headers": ["TEAM_ID", "PLAYER_ID", "POSITION"], "rowSet": []}
        ]
    }


def _schedule_fetcher(season: str) -> list[ScheduleRow]:
    rows = json.loads(SCHEDULE_FIXTURE.read_text())
    return [ScheduleRow(**row) for row in rows]


def _source() -> SourceRef:
    return SourceRef(
        source="Test Wire",
        url="https://example.com/wire/test",
        retrieved="2026-08-01",
        season_label="2026-27",
        quality_tier="very_high",
        type="news",
    )


def _transaction(player: str, to_team: str, date: str) -> TransactionEvent:
    return TransactionEvent(
        player=player, from_team=None, to_team=to_team, kind="trade", date=date, source=_source()
    )


def _season_line(player_id: int, name: str, games: int, minutes: float) -> SeasonLine:
    return SeasonLine(
        season="2025-26", player_id=player_id, name=name, team="ATL", position="G", age=25.0,
        games=games, minutes=minutes, fgm=5.0, fga=10.0, ftm=2.0, fta=2.5, tpm=1.0, pts=13.0,
        reb=4.0, ast=3.0, stl=1.0, blk=0.5, tov=1.5,
    )


def test_min_rankable_minutes_gate_excludes_tiny_sample_keeps_real_sample() -> None:
    # B3: a 3gp x 22min cameo (66 blend-window minutes) is a tiny sample and
    # must not make the board; a 60gp x 30min regular (1800 minutes) clears
    # min_rankable_minutes (300) easily and must still rank
    settings = load_settings(SHIPPED_SETTINGS)
    lines_by_season = {
        "2025-26": [
            _season_line(1, "Cameo Player", games=3, minutes=22.0),
            _season_line(2, "Regular Player", games=60, minutes=30.0),
        ],
    }
    store = EvidenceStore()
    schedule = fetch_schedule("2026-27", fetcher=lambda season: [])  # ScheduleUnavailable

    result = run_pipeline(settings, lines_by_season, store, schedule, projection_date="2026-08-12")

    assert "1" not in result.records
    assert "2" in result.records


@pytest.fixture()
def dataset_paths(tmp_path: Path) -> dict[str, Path]:
    """Build a small PipelineResult over the existing fixtures and export it."""
    settings = load_settings(SHIPPED_SETTINGS)
    lines_by_season = {
        "2025-26": fetch_season_averages(
            "2025-26", fetcher=_stats_fetcher, roster_fetcher=_roster_fetcher
        )
    }
    store = load_store(RESEARCH_DIR, settings)
    # the leaguedash fixture's teams (ATL/BOS) and the rookie's team ("Test
    # Town Titans") deliberately don't match the schedule fixture's teams
    # (AAA/BBB/CCC) -- every player exercises the schedule-unavailable fallback
    schedule = fetch_schedule("2026-27", fetcher=_schedule_fetcher)

    result = run_pipeline(settings, lines_by_season, store, schedule, projection_date="2026-08-12")

    output_path = tmp_path / "players_2026_27.json"
    csv_path = tmp_path / "projections_2026_27.csv"
    sources_path = tmp_path / "sources.json"
    build_dataset(result, settings, output_path, csv_path, sources_path)

    return {"output": output_path, "csv": csv_path, "sources": sources_path}


def test_build_dataset_writes_valid_schema(dataset_paths: dict[str, Path]) -> None:
    payload = json.loads(dataset_paths["output"].read_text())

    assert payload["season"] == "2026-27"
    assert payload["projection_date"] == "2026-08-12"
    assert "settings" in payload and payload["settings"]["season"] == "2026-27"
    assert isinstance(payload["schedule_available"], bool)

    players = payload["players"]
    assert players, "expected at least one projected player"

    player_one = players[0]
    for block in _PLAYER_BLOCKS:
        assert block in player_one, f"missing block {block!r}"

    fg_pct = player_one["projection"]["fg_pct"]
    ft_pct = player_one["projection"]["ft_pct"]
    assert 0.0 <= fg_pct <= 1.0
    assert 0.0 <= ft_pct <= 1.0

    # punt-build feature needs per-category availability-adjusted z-scores
    # alongside the existing aggregate -- same 9-key dict shape as
    # per_game_zscores, straight off PlayerValue.availability_adjusted_zscores
    assert "availability_adjusted_zscores" in player_one["fantasy"]
    assert set(player_one["fantasy"]["availability_adjusted_zscores"].keys()) == set(
        player_one["fantasy"]["per_game_zscores"].keys()
    )
    assert len(player_one["fantasy"]["availability_adjusted_zscores"]) == 9

    # ranks are dense and contiguous starting at 1
    ranks = [p["rank"] for p in players]
    assert ranks == list(range(1, len(players) + 1))

    # the fixture-projected rookie made it into the pool
    assert any(p["player_id"].startswith("rookie-") for p in players)


def _atl_bos_schedule_fetcher(season: str) -> list[ScheduleRow]:
    # mirrors schedule_2026_27_sample.json's AAA/BBB date pattern (weeks
    # 18-20 only) but renamed to this test's real player teams (ATL/BOS) so
    # playoff_games is non-degenerate -- dataset_paths' fixture deliberately
    # mismatches teams to exercise the "team not in schedule" 0-game path,
    # this fetcher exercises real per-window hand-counted numbers instead
    return [
        ScheduleRow(game_date="2027-02-17", home_team_abbr="ATL", away_team_abbr="BOS"),
        ScheduleRow(game_date="2027-02-20", home_team_abbr="BOS", away_team_abbr="ATL"),
        ScheduleRow(game_date="2027-02-21", home_team_abbr="ATL", away_team_abbr="BOS"),
        ScheduleRow(game_date="2027-02-22", home_team_abbr="BOS", away_team_abbr="ATL"),
        ScheduleRow(game_date="2027-02-24", home_team_abbr="ATL", away_team_abbr="BOS"),
        ScheduleRow(game_date="2027-02-28", home_team_abbr="BOS", away_team_abbr="ATL"),
        ScheduleRow(game_date="2027-03-01", home_team_abbr="ATL", away_team_abbr="BOS"),
        ScheduleRow(game_date="2027-03-04", home_team_abbr="BOS", away_team_abbr="ATL"),
        ScheduleRow(game_date="2027-03-07", home_team_abbr="ATL", away_team_abbr="BOS"),
    ]


def test_build_dataset_windows_map_hand_counted_per_window(tmp_path: Path) -> None:
    # ATL plays every one of the 9 rows above; hand count by fantasy week
    # (Mon-Sun, week1 starting 2026-10-19 per settings.json):
    # wk18(02-15..21): 02-17,02-20,02-21 -> 3; wk19(02-22..28): 02-22,02-24,02-28
    # -> 3; wk20(03-01..07): 03-01,03-04,03-07 -> 3; wk17/21/22 -> 0.
    # windows: 17-19 -> 0+3+3=6; 18-20 -> 3+3+3=9; 19-21 -> 3+3+0=6;
    # 20-22 -> 3+0+0=3; 21-23 -> 0; 22-24 -> 0
    settings = load_settings(SHIPPED_SETTINGS)
    lines_by_season = {
        "2025-26": fetch_season_averages(
            "2025-26", fetcher=_stats_fetcher, roster_fetcher=_roster_fetcher
        )
    }
    store = load_store(RESEARCH_DIR, settings)
    schedule = fetch_schedule("2026-27", fetcher=_atl_bos_schedule_fetcher)

    result = run_pipeline(settings, lines_by_season, store, schedule, projection_date="2026-08-12")
    output_path = tmp_path / "players_2026_27.json"
    build_dataset(result, settings, output_path, tmp_path / "p.csv", tmp_path / "sources.json")

    payload = json.loads(output_path.read_text())
    atl_guard = next(p for p in payload["players"] if p["player_id"] == "9000001")
    windows = atl_guard["schedule"]["windows"]

    assert windows["17-19"]["playoff_games"] == 6
    assert windows["18-20"]["playoff_games"] == 9
    assert windows["19-21"]["playoff_games"] == 6
    assert windows["20-22"]["playoff_games"] == 3
    # a window entirely past this (real, successfully-fetched) schedule's last
    # game is a real, documented 0 -- not force-nulled, since the shared
    # force-unavailable decision is keyed on the DEFAULT window (19-21) alone,
    # which does have real games here
    assert windows["21-23"]["playoff_games"] == 0
    assert windows["22-24"]["playoff_games"] == 0
    # default top-level fields mirror the "19-21" entry exactly
    assert atl_guard["schedule"]["playoff_games"] == windows["19-21"]["playoff_games"]


def test_build_dataset_windows_map_has_six_keys_and_default_identity(
    dataset_paths: dict[str, Path],
) -> None:
    payload = json.loads(dataset_paths["output"].read_text())
    assert payload["candidate_windows"] == ["17-19", "18-20", "19-21", "20-22", "21-23", "22-24"]
    assert payload["default_window"] == "19-21"

    for player in payload["players"]:
        schedule = player["schedule"]
        windows = schedule["windows"]
        assert set(windows.keys()) == set(payload["candidate_windows"])

        # back-compat: the shipped top-level fields are exactly the "19-21"
        # windows-map entry -- both built off the same window_profiles/
        # window_values in pipeline.py, not two independently-computed copies
        default_entry = windows["19-21"]
        assert default_entry["week_games"] == schedule["week_games"]
        assert default_entry["playoff_games"] == schedule["playoff_games"]
        assert default_entry["playoff_b2bs"] == schedule["playoff_b2bs"]
        assert default_entry["playoff_schedule_score"] == schedule["playoff_schedule_score"]
        assert default_entry["expected_playoff_games"] == schedule["expected_playoff_games"]
        assert default_entry["playoff_value_z"] == player["fantasy"]["playoff_value"]


def test_build_dataset_team_not_in_schedule_degrades_to_zero_not_null(
    dataset_paths: dict[str, Path],
) -> None:
    # deliberate fixture team mismatch (see dataset_paths' comment): the
    # schedule itself fetched fine, so playoff_profile() finds every one of
    # our players' teams simply absent from it -- schedule.py's own fallback
    # for "team not in this (available) schedule" is a real 0-game profile,
    # not a null one (that null path is only for a whole-schedule fetch
    # failure, covered separately below)
    payload = json.loads(dataset_paths["output"].read_text())
    assert payload["schedule_available"] is True
    for player in payload["players"]:
        schedule = player["schedule"]
        assert schedule["week_games"] is not None
        assert schedule["playoff_games"] == 0
        assert schedule["playoff_b2bs"] == 0
        assert schedule["playoff_schedule_score"] is not None
        assert schedule["expected_playoff_games"] == 0.0


def test_build_dataset_schedule_unavailable_nulls_every_player(tmp_path: Path) -> None:
    # a genuine fetch failure (empty schedule rows -> ScheduleUnavailable, per
    # nineproj.data.schedule's D6 contract) is the actual null-fields path
    settings = load_settings(SHIPPED_SETTINGS)
    lines_by_season = {
        "2025-26": fetch_season_averages(
            "2025-26", fetcher=_stats_fetcher, roster_fetcher=_roster_fetcher
        )
    }
    store = load_store(RESEARCH_DIR, settings)
    schedule = fetch_schedule("2026-27", fetcher=lambda season: [])

    result = run_pipeline(settings, lines_by_season, store, schedule, projection_date="2026-08-12")
    output_path = tmp_path / "players_2026_27.json"
    build_dataset(result, settings, output_path, tmp_path / "p.csv", tmp_path / "sources.json")

    payload = json.loads(output_path.read_text())
    assert payload["schedule_available"] is False
    # never fetched at all -- not the "forced unavailable" empty-window path
    assert payload["playoff_window_force_unavailable"] is False
    assert payload["players"], "expected players even with no schedule"
    for player in payload["players"]:
        schedule_block = player["schedule"]
        assert schedule_block["week_games"] is None
        assert schedule_block["playoff_games"] is None
        assert schedule_block["playoff_b2bs"] is None
        assert schedule_block["playoff_schedule_score"] is None
        assert schedule_block["expected_playoff_games"] is None
        # a whole-schedule fetch failure nulls every candidate window too, not
        # just the shipped default
        for window_entry in schedule_block["windows"].values():
            assert window_entry["week_games"] is None
            assert window_entry["playoff_games"] is None
            assert window_entry["playoff_b2bs"] is None
            assert window_entry["playoff_schedule_score"] is None
            assert window_entry["expected_playoff_games"] is None
            assert window_entry["playoff_value_z"] is None


def test_build_dataset_playoff_window_empty_league_wide_forces_unavailable(tmp_path: Path) -> None:
    # a real, successfully-fetched schedule (e.g. the NBA's partial
    # early-release schedule, ~10 games/team with nothing past January) whose
    # playoff window (weeks 19-21, 2027-02-22..03-14) has zero games for
    # EVERY team in the league -- not just our players' teams -- must be
    # treated as unpublished (D6), not as a real "0 playoff games" result
    settings = load_settings(SHIPPED_SETTINGS)
    lines_by_season = {
        "2025-26": fetch_season_averages(
            "2025-26", fetcher=_stats_fetcher, roster_fetcher=_roster_fetcher
        )
    }
    store = load_store(RESEARCH_DIR, settings)

    def _out_of_window_schedule_fetcher(season: str) -> list[ScheduleRow]:
        # all games in November 2026, well before the Feb-Mar playoff window
        return [
            ScheduleRow(game_date="2026-11-03", home_team_abbr="XXX", away_team_abbr="YYY"),
            ScheduleRow(game_date="2026-11-10", home_team_abbr="YYY", away_team_abbr="XXX"),
        ]

    schedule = fetch_schedule("2026-27", fetcher=_out_of_window_schedule_fetcher)

    result = run_pipeline(settings, lines_by_season, store, schedule, projection_date="2026-08-12")
    output_path = tmp_path / "players_2026_27.json"
    build_dataset(result, settings, output_path, tmp_path / "p.csv", tmp_path / "sources.json")

    payload = json.loads(output_path.read_text())
    assert payload["schedule_available"] is False
    assert payload["playoff_window_force_unavailable"] is True
    for player in payload["players"]:
        schedule_block = player["schedule"]
        assert schedule_block["week_games"] is None
        assert schedule_block["playoff_games"] is None
        assert schedule_block["playoff_b2bs"] is None
        assert schedule_block["playoff_schedule_score"] is None
        assert schedule_block["expected_playoff_games"] is None
        assert player["fantasy"]["playoff_value"] is None
        # this run's league-wide zero is specific to the DEFAULT window
        # (19-21); the force-unavailable decision still applies uniformly to
        # every candidate window (see pipeline.py's window_profiles loop)
        for window_entry in schedule_block["windows"].values():
            assert window_entry["playoff_games"] is None
            assert window_entry["playoff_value_z"] is None

    report_path = tmp_path / "report.json"
    ok = validate_dataset(output_path, report_path)
    report = json.loads(report_path.read_text())
    assert ok is True
    coverage = next(c for c in report["checks"] if c["check"] == "playoff_window_coverage")
    assert coverage["status"] == "warn"


def test_csv_header_matches_backend_import_contract(dataset_paths: dict[str, Path]) -> None:
    with dataset_paths["csv"].open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = tuple(next(reader))
    assert header == _CSV_HEADER


def test_sources_json_refreshed_with_nba_stats_provenance(dataset_paths: dict[str, Path]) -> None:
    payload = json.loads(dataset_paths["sources"].read_text())
    assert "nba_stats_endpoints" in payload
    assert any(e["season"] == "2025-26" for e in payload["nba_stats_endpoints"])
    assert "generated" in payload


def test_validate_dataset_passes_on_the_export_itself(dataset_paths: dict[str, Path], tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    ok = validate_dataset(dataset_paths["output"], report_path)
    report = json.loads(report_path.read_text())
    assert ok is True, report
    assert report["status"] == "pass"
    # a fixture pool this small is always a documented shortfall, not a failure
    player_count = next(c for c in report["checks"] if c["check"] == "player_count")
    assert player_count["status"] == "warn"
    # the schedule fixture has real league-wide playoff-window games (AAA/BBB/CCC)
    coverage = next(c for c in report["checks"] if c["check"] == "playoff_window_coverage")
    assert coverage["status"] == "pass"


def test_validate_dataset_with_store_flags_unmatched_consensus_names(
    dataset_paths: dict[str, Path], tmp_path: Path
) -> None:
    # the fixture consensus list's "Test Star A".."Test Star E" don't match
    # any of the leaguedash/rookie fixture's names -- reverse-diff coverage
    settings = load_settings(SHIPPED_SETTINGS)
    store = load_store(RESEARCH_DIR, settings)

    report_path = tmp_path / "report_with_store.json"
    ok = validate_dataset(dataset_paths["output"], report_path, store=store)
    report = json.loads(report_path.read_text())

    assert ok is True, report
    diff = report["analysis"]["consensus_pool_diff"]
    unmatched_names = {entry["name"] for entry in diff["unmatched_consensus_names"]}
    assert "Test Star A" in unmatched_names
    matching_entry = next(e for e in diff["unmatched_consensus_names"] if e["name"] == "Test Star A")
    assert matching_entry["source"] == "Test Rankings Site"


def test_validate_dataset_without_store_omits_unmatched_consensus_names(
    dataset_paths: dict[str, Path], tmp_path: Path
) -> None:
    report_path = tmp_path / "report_no_store.json"
    validate_dataset(dataset_paths["output"], report_path)
    report = json.loads(report_path.read_text())
    assert report["analysis"]["consensus_pool_diff"]["unmatched_consensus_names"] is None


def test_validate_dataset_catches_corrupted_ranks_and_percentages(
    dataset_paths: dict[str, Path], tmp_path: Path
) -> None:
    payload = json.loads(dataset_paths["output"].read_text())
    corrupted = copy.deepcopy(payload)
    assert len(corrupted["players"]) >= 2, "need at least 2 players to inject a duplicate rank"

    # duplicate rank: player[1] takes player[0]'s rank
    corrupted["players"][1]["rank"] = corrupted["players"][0]["rank"]
    # out-of-bounds FG%
    corrupted["players"][0]["projection"]["fg_pct"] = 1.5

    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text(json.dumps(corrupted))
    report_path = tmp_path / "corrupt_report.json"

    ok = validate_dataset(corrupt_path, report_path)
    report = json.loads(report_path.read_text())

    assert ok is False
    assert report["status"] == "fail"
    checks_by_name = {c["check"]: c["status"] for c in report["checks"]}
    assert checks_by_name["rank_contiguity"] == "fail"
    assert checks_by_name["pct_bounds"] == "fail"


def test_validate_dataset_catches_out_of_range_window_games_and_score(
    dataset_paths: dict[str, Path], tmp_path: Path
) -> None:
    payload = json.loads(dataset_paths["output"].read_text())
    corrupted = copy.deepcopy(payload)
    player = corrupted["players"][0]
    # "18-20" is a 3-week window -> max 21 games; 999 and a score of 1.5 are
    # both out of bounds
    player["schedule"]["windows"]["18-20"]["playoff_games"] = 999
    player["schedule"]["windows"]["18-20"]["playoff_schedule_score"] = 1.5

    corrupt_path = tmp_path / "corrupt_windows.json"
    corrupt_path.write_text(json.dumps(corrupted))
    report_path = tmp_path / "corrupt_windows_report.json"

    ok = validate_dataset(corrupt_path, report_path)
    report = json.loads(report_path.read_text())

    assert ok is False
    checks_by_name = {c["check"]: c for c in report["checks"]}
    assert checks_by_name["windows_games_bounds"]["status"] == "fail"
    assert player["name"] in checks_by_name["windows_games_bounds"]["detail"]
    assert checks_by_name["windows_score_range"]["status"] == "warn"


def test_current_team_resolution_uses_transaction_date_not_encounter_order() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    lines_by_season = {
        "2025-26": fetch_season_averages(
            "2025-26", fetcher=_stats_fetcher, roster_fetcher=_roster_fetcher
        )
    }
    schedule = fetch_schedule("2026-27", fetcher=_schedule_fetcher)

    # encounter order alone (last-in-list) would pick "Team July" (wrong) --
    # the August transaction is dated later but listed first in the store
    store = EvidenceStore(
        transactions=[
            _transaction("Test Guard A", "Team August", "2026-08-10"),
            _transaction("Test Guard A", "Team July", "2026-07-01"),
        ]
    )

    result = run_pipeline(settings, lines_by_season, store, schedule, projection_date="2026-08-12")
    pid = "9000001"  # Test Guard A, per leaguedash_2025_26_sample.json

    assert result.records[pid].team == "Team August"
    assert result.old_team[pid] == "ATL"
    assert result.team_changed[pid] is True


def test_current_team_resolution_tie_or_undated_keeps_encounter_order() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    lines_by_season = {
        "2025-26": fetch_season_averages(
            "2025-26", fetcher=_stats_fetcher, roster_fetcher=_roster_fetcher
        )
    }
    schedule = fetch_schedule("2026-27", fetcher=_schedule_fetcher)

    # both dates empty (unparseable) -- a tie on the (0, 0, 0) sort key falls
    # back to encounter order, so the last-listed transaction still wins
    store = EvidenceStore(
        transactions=[
            _transaction("Test Guard A", "Team First", ""),
            _transaction("Test Guard A", "Team Second", ""),
        ]
    )

    result = run_pipeline(settings, lines_by_season, store, schedule, projection_date="2026-08-12")
    pid = "9000001"

    assert result.records[pid].team == "Team Second"


def test_consensus_top50_in_pool_fails_when_a_top50_name_is_missing_from_pool(
    dataset_paths: dict[str, Path], tmp_path: Path
) -> None:
    # the fixture consensus list is "Test Star A".."Test Star E" (5 names,
    # so all inside any list's top 50) -- a pool missing "Test Star C" must fail
    settings = load_settings(SHIPPED_SETTINGS)
    store = load_store(RESEARCH_DIR, settings)
    report_path = tmp_path / "report.json"
    pool_names = {"Test Star A", "Test Star B", "Test Star D", "Test Star E"}

    ok = validate_dataset(dataset_paths["output"], report_path, store=store, pool_names=pool_names)
    report = json.loads(report_path.read_text())

    assert ok is False
    check = next(c for c in report["checks"] if c["check"] == "consensus_top50_in_pool")
    assert check["status"] == "fail"
    assert "Test Star C" in check["detail"]


def test_consensus_top50_in_pool_passes_when_every_top50_name_matches(
    dataset_paths: dict[str, Path], tmp_path: Path
) -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    store = load_store(RESEARCH_DIR, settings)
    report_path = tmp_path / "report.json"
    pool_names = {"Test Star A", "Test Star B", "Test Star C", "Test Star D", "Test Star E"}

    ok = validate_dataset(dataset_paths["output"], report_path, store=store, pool_names=pool_names)
    report = json.loads(report_path.read_text())

    assert ok is True
    check = next(c for c in report["checks"] if c["check"] == "consensus_top50_in_pool")
    assert check["status"] == "pass"


def test_consensus_top50_in_pool_omitted_without_pool_names(
    dataset_paths: dict[str, Path], tmp_path: Path
) -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    store = load_store(RESEARCH_DIR, settings)
    report_path = tmp_path / "report.json"

    ok = validate_dataset(dataset_paths["output"], report_path, store=store)
    report = json.loads(report_path.read_text())

    assert ok is True
    assert not any(c["check"] == "consensus_top50_in_pool" for c in report["checks"])


def test_validate_dataset_fails_on_zero_players(tmp_path: Path) -> None:
    empty_payload = {
        "season": "2026-27",
        "projection_date": "2026-08-12",
        "last_updated": "2026-08-12T00:00:00+00:00",
        "settings": {},
        "schedule_available": False,
        "players": [],
    }
    empty_path = tmp_path / "empty.json"
    empty_path.write_text(json.dumps(empty_payload))
    report_path = tmp_path / "empty_report.json"

    ok = validate_dataset(empty_path, report_path)
    report = json.loads(report_path.read_text())

    assert ok is False
    assert report["status"] == "fail"
    player_count = next(c for c in report["checks"] if c["check"] == "player_count")
    assert player_count["status"] == "fail"
