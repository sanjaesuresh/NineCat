#!/usr/bin/env python3
"""CLI orchestrator: run the full 2026-27 projection pipeline end-to-end.

Wires every nineproj stage (season fetch -> universe -> baseline -> role/env
adjustment -> availability -> schedule/playoff -> value -> consensus ->
composite -> export -> validate) behind one command. `--offline` forces a
cache/fixtures-only run (used by the end-to-end test and CI); the process
exit code reports which stage failed rather than always being 0/1.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from nineproj.config import load_settings
from nineproj.data.nba_stats import SeasonLine, fetch_season_averages
from nineproj.data.schedule import Schedule, ScheduleRow, fetch_schedule
from nineproj.export.dataset import build_dataset
from nineproj.export.pipeline import run_pipeline
from nineproj.export.validate import validate_dataset
from nineproj.research.store import load_store
from nineproj.utils.cache import cached_fetch

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
_SETTINGS_PATH = _ROOT / "config" / "settings.json"

# exit codes: 0 ok, 1 --validate-store failure, 2 dataset validation failure,
# 3 season/evidence data acquisition failure (e.g. offline + cold cache)
_EXIT_VALIDATE_STORE_FAILED = 1
_EXIT_VALIDATION_FAILED = 2
_EXIT_DATA_ACQUISITION_FAILED = 3


def _offline_stats_fetcher(cache_dir: Path | None, ttl_hours: float):
    """Cache-or-fail: never imports/calls nba_api, so a cold cache raises loudly.

    serve_expired=True (H2): an expired-but-present cache file is served
    as-is, no retry/backoff cost -- offline mode never has a live fetch to
    retry toward anyway, so paying that cost was pure waste (~13 minutes
    across a full universe's roster fetches).
    """

    def fetcher(season: str) -> dict:
        def _raise() -> None:
            raise RuntimeError(f"offline mode: live NBA Stats fetch forbidden (season={season})")

        return cached_fetch(
            f"leaguedash_{season}",
            ttl_hours,
            _raise,
            cache_dir=cache_dir,
            endpoint="leaguedashplayerstats",
            serve_expired=True,
        )

    return fetcher


def _offline_roster_fetcher(cache_dir: Path | None, ttl_hours: float):
    def fetcher(season: str, team_id: int) -> dict:
        def _raise() -> None:
            raise RuntimeError(
                f"offline mode: live roster fetch forbidden (team_id={team_id}, season={season})"
            )

        return cached_fetch(
            f"roster_{season}_{team_id}",
            ttl_hours,
            _raise,
            cache_dir=cache_dir,
            endpoint="commonteamroster",
            serve_expired=True,
        )

    return fetcher


def _schedule_fetcher(cache_dir: Path | None, ttl_hours: float, offline: bool):
    """Mirrors nineproj.data.schedule's own default fetcher, but cache-dir-aware.

    schedule.py's default fetcher hardcodes DEFAULT_CACHE_DIR with no
    cache_dir passthrough (unlike fetch_season_averages), so the CLI needs its
    own copy to honor --cache-dir; in --offline mode it never imports nba_api.
    """

    def fetcher(season: str) -> list[ScheduleRow]:
        def _fetch_live() -> list[list[str]]:
            if offline:
                raise RuntimeError(f"offline mode: live schedule fetch forbidden (season={season})")

            from nba_api.stats.endpoints import scheduleleaguev2

            response = scheduleleaguev2.ScheduleLeagueV2(season=season)
            payload = response.season_games.get_dict()
            headers: list[str] = payload["headers"]

            def col(row: list, name: str) -> object:
                return row[headers.index(name)]

            return [
                [
                    str(col(row, "gameDateEst"))[:10],
                    str(col(row, "homeTeam_teamTricode")),
                    str(col(row, "awayTeam_teamTricode")),
                ]
                for row in payload["data"]
            ]

        raw_rows = cached_fetch(
            f"schedule_{season}",
            ttl_hours,
            _fetch_live,
            cache_dir=cache_dir,
            endpoint="scheduleleaguev2",
            # offline: a live fetch is forbidden anyway, so serve an expired
            # cache as-is rather than pay the retry/backoff cost first (H2)
            serve_expired=offline,
        )
        return [ScheduleRow(*row) for row in raw_rows]

    return fetcher


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the nineproj 2026-27 projection pipeline.")
    parser.add_argument(
        "--offline", action="store_true", help="cache/fixtures only, never call nba_api live"
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--research-dir", type=Path, default=_ROOT / "data" / "research")
    parser.add_argument("--output", type=Path, default=_ROOT / "data" / "players_2026_27.json")
    parser.add_argument("--csv", type=Path, default=_ROOT / "data" / "projections_2026_27.csv")
    parser.add_argument("--sources", type=Path, default=_ROOT / "data" / "sources.json")
    parser.add_argument("--report", type=Path, default=_ROOT / "validation" / "report.json")
    parser.add_argument(
        "--validate-store", action="store_true", help="only load_store(research_dir); exit 0/1"
    )
    parser.add_argument("--projection-date", type=str, default=date.today().isoformat())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)

    settings = load_settings(_SETTINGS_PATH)
    logger.info("stage=settings season=%s prior_seasons=%s", settings.season, settings.prior_seasons)

    if args.validate_store:
        try:
            store = load_store(args.research_dir, settings)
        except Exception as exc:
            logger.error("stage=validate_store failed error=%s", exc)
            return _EXIT_VALIDATE_STORE_FAILED
        logger.info(
            "stage=validate_store ok roles=%d injuries=%d rookies=%d transactions=%d "
            "sentiment=%d consensus_lists=%d",
            len(store.roles), len(store.injuries), len(store.rookies), len(store.transactions),
            len(store.sentiment), len(store.consensus_lists),
        )
        return 0

    ttl_hours = float(settings.cache.ttl_hours)
    stats_fetcher = _offline_stats_fetcher(args.cache_dir, ttl_hours) if args.offline else None
    roster_fetcher = _offline_roster_fetcher(args.cache_dir, ttl_hours) if args.offline else None

    lines_by_season: dict[str, list[SeasonLine]] = {}
    try:
        for season in settings.prior_seasons:
            # H3: thread the real settings.cache.ttl_hours through even on the
            # live (non-offline) path, where fetcher/roster_fetcher are None
            # and fetch_season_averages would otherwise fall back to its own
            # hardcoded default -- settings.cache.ttl_hours was inert before this
            lines = fetch_season_averages(
                season,
                fetcher=stats_fetcher,
                roster_fetcher=roster_fetcher,
                cache_dir=args.cache_dir,
                ttl_hours=ttl_hours,
            )
            lines_by_season[season] = lines
            logger.info("stage=fetch_season season=%s players=%d", season, len(lines))
    except Exception as exc:
        # offline + cold cache (or a live fetch that exhausts retries with no
        # stale fallback) leaves no usable season data -- fail loudly rather
        # than run a projection over an empty/partial universe
        logger.error("stage=fetch_season failed: %s", exc)
        return _EXIT_DATA_ACQUISITION_FAILED

    try:
        store = load_store(args.research_dir, settings)
    except Exception as exc:
        logger.error("stage=load_store failed: %s", exc)
        return _EXIT_DATA_ACQUISITION_FAILED
    logger.info(
        "stage=load_store roles=%d injuries=%d rookies=%d transactions=%d sentiment=%d consensus_lists=%d",
        len(store.roles), len(store.injuries), len(store.rookies), len(store.transactions),
        len(store.sentiment), len(store.consensus_lists),
    )

    # schedule fetch failure is not fatal (D6): downstream falls back to the
    # all-None UnavailableProfile path rather than aborting the whole run
    schedule = fetch_schedule(settings.season, fetcher=_schedule_fetcher(args.cache_dir, ttl_hours, args.offline))
    logger.info("stage=fetch_schedule available=%s", isinstance(schedule, Schedule))

    result = run_pipeline(settings, lines_by_season, store, schedule, args.projection_date)
    logger.info("stage=pipeline players=%d", len(result.records))

    build_dataset(result, settings, args.output, args.csv, args.sources)
    logger.info("stage=export output=%s csv=%s sources=%s", args.output, args.csv, args.sources)

    # B1: the full pipeline pool (pre-200-cut), not just the exported top 200
    # -- so consensus_top50_in_pool can catch a real, consensus-ranked player
    # who never even made the pool
    pool_names = {record.name for record in result.records.values()}
    ok = validate_dataset(args.output, args.report, store=store, pool_names=pool_names)
    logger.info("stage=validate ok=%s report=%s", ok, args.report)

    return 0 if ok else _EXIT_VALIDATION_FAILED


if __name__ == "__main__":
    sys.exit(main())
