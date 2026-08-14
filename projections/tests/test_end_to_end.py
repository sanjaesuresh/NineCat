"""End-to-end smoke test: `run_projection.py --offline` over fixture data (Task 14)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from nineproj.utils.cache import cached_fetch

PROJ_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
LEAGUEDASH_FIXTURE = FIXTURES / "leaguedash_2025_26_sample.json"
SCHEDULE_FIXTURE = FIXTURES / "schedule_2026_27_sample.json"
# a copy of fixtures/research/ minus its consensus list: that list's names
# ("Test Star A".."E") deliberately don't match the leaguedash fixture's
# players elsewhere (test_export.py's unmatched-consensus-name coverage) --
# now that run_projection.py always wires pool_names into validate_dataset,
# that mismatch would trip the new consensus_top50_in_pool fail check here
# too, which isn't this smoke test's concern (pipeline mechanics, not
# consensus-name fidelity)
RESEARCH_DIR = FIXTURES / "research_e2e"

# mirrors config/settings.json's prior_seasons -- the CLI fetches all three
_PRIOR_SEASONS = ("2025-26", "2024-25", "2023-24")

# ATL/BOS team_ids present in the leaguedash fixture (see leaguedash_2025_26_sample.json)
_FIXTURE_TEAM_IDS = (1610612737, 1610612738)
_EMPTY_ROSTER = {
    "resultSets": [{"name": "CommonTeamRoster", "headers": ["TEAM_ID", "PLAYER_ID", "POSITION"], "rowSet": []}]
}


def _seed_cache(cache_dir: Path) -> None:
    """Pre-seed cache_dir with fixture payloads through cached_fetch itself
    (not a hand-built JSON file), so the on-disk envelope always matches
    whatever cache.py actually writes -- offline mode then reads it back
    without ever calling a live fetcher.
    """
    stats_payload = json.loads(LEAGUEDASH_FIXTURE.read_text())
    for season in _PRIOR_SEASONS:
        # same fixture content reused under every season key: SeasonLine.season
        # is stamped from fetch_season_averages' own `season` arg, not the
        # payload, so this is a legitimate synthetic 3-season smoke-test seed
        cached_fetch(
            f"leaguedash_{season}", 24, lambda: stats_payload, cache_dir=cache_dir,
            endpoint="leaguedashplayerstats",
        )
        # rosters aren't exercised by this smoke test (positions aren't
        # asserted on) -- seeded empty just to skip the offline
        # fetch-fails-3x-with-backoff retry cost per team per season
        for team_id in _FIXTURE_TEAM_IDS:
            cached_fetch(
                f"roster_{season}_{team_id}", 24, lambda: _EMPTY_ROSTER, cache_dir=cache_dir,
                endpoint="commonteamroster",
            )

    schedule_rows = json.loads(SCHEDULE_FIXTURE.read_text())
    # cached_fetch persists exactly what fetch_fn returns; the schedule
    # fetcher's own cache format is a list of [date, home, away] rows (see
    # nineproj.data.schedule's _default_fetcher), not ScheduleRow objects
    raw_rows = [[r["game_date"], r["home_team_abbr"], r["away_team_abbr"]] for r in schedule_rows]
    cached_fetch(
        "schedule_2026-27", 24, lambda: raw_rows, cache_dir=cache_dir, endpoint="scheduleleaguev2"
    )


def test_offline_run_exits_zero_and_produces_a_valid_ranked_dataset(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _seed_cache(cache_dir)

    output_path = tmp_path / "players_2026_27.json"
    csv_path = tmp_path / "projections_2026_27.csv"
    sources_path = tmp_path / "sources.json"
    report_path = tmp_path / "report.json"

    proc = subprocess.run(
        [
            sys.executable, str(PROJ_ROOT / "run_projection.py"),
            "--offline",
            "--cache-dir", str(cache_dir),
            "--research-dir", str(RESEARCH_DIR),
            "--output", str(output_path),
            "--csv", str(csv_path),
            "--sources", str(sources_path),
            "--report", str(report_path),
            "--projection-date", "2026-08-12",
        ],
        cwd=PROJ_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    payload = json.loads(output_path.read_text())
    assert payload["players"], "expected at least one ranked player"
    ranks = [p["rank"] for p in payload["players"]]
    assert ranks == list(range(1, len(ranks) + 1))

    report = json.loads(report_path.read_text())
    assert report["status"] in ("pass", "fail")
    player_count = next(c for c in report["checks"] if c["check"] == "player_count")
    # the fixture research/stats pool is far smaller than 200 -- a documented
    # shortfall (warn), not a failure
    assert player_count["status"] == "warn"
