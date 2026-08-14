"""Validate players_2026_27.json's schema/bounds and write validation/report.json.

Every check is a named entry in the report so a failure is diagnosable
without re-reading this module; only hard schema/bounds violations flip the
overall status to "fail" (and this function's return to False) -- a
documented player-count shortfall is a "warn", since a small research pool
is a legitimate run, not a bug.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from nineproj.research.store import EvidenceStore, normalize_name

_TOP_N = 200

_RAW_STAT_FIELDS = (
    "points", "rebounds", "assists", "steals", "blocks", "three_pm",
    "turnovers", "fga", "fta", "fgm", "ftm",
)


def _check(checks: list[dict], name: str, ok: bool, detail: str, *, warn: bool = False) -> None:
    status = "pass" if ok else ("warn" if warn else "fail")
    checks.append({"check": name, "status": status, "detail": detail})


def _write_report(report_path: str | Path, report: dict) -> None:
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))


def validate_dataset(
    json_path: str | Path,
    report_path: str | Path,
    store: EvidenceStore | None = None,
    pool_names: set[str] | None = None,
) -> bool:
    """Validate the exported dataset at json_path; write report_path; return pass/fail.

    `store` is optional (accepts an already-loaded EvidenceStore rather than a
    research_dir/settings_path pair, so this module never needs to know how to
    load settings itself) -- when provided, the consensus-pool diff also
    covers its "consensus-list name never matched a projected player" half;
    without it, that half is just omitted (documented in the report note)
    rather than the whole check failing.

    `pool_names` (extended the same way `store` was) is the full PIPELINE
    POOL of player names -- every player who survived the valuation gate,
    not just the exported top 200 -- so B1's consensus_top50_in_pool check
    can catch a consensus-listed player (e.g. a returner) who never even made
    the pool, which the 200-only unmatched_consensus_names diff can't see.
    Requires both `store` and `pool_names`; the check is simply omitted
    (not run, not warned) when either is missing.
    """
    json_path = Path(json_path)
    checks: list[dict] = []

    try:
        payload = json.loads(json_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _check(checks, "json_parses", False, f"{json_path}: {exc}")
        _write_report(
            report_path,
            {
                "generated": datetime.now(timezone.utc).isoformat(),
                "status": "fail",
                "checks": checks,
                "analysis": {},
            },
        )
        return False
    _check(checks, "json_parses", True, "dataset JSON parsed successfully")

    players: list[dict] = payload.get("players", [])
    n = len(players)

    # 0 players is a hard failure (nothing to project, not a "small pool"),
    # but any documented shortfall 1..199 is a legitimate small-research-pool
    # run, not a defect
    _check(
        checks, "player_count", n == _TOP_N, f"{n} players (expected {_TOP_N})",
        warn=(0 < n != _TOP_N),
    )

    ranks = [p["rank"] for p in players]
    contiguous = sorted(ranks) == list(range(1, n + 1))
    _check(checks, "rank_contiguity", contiguous, f"ranks unique+contiguous 1..{n}: {contiguous}")

    ids = [p["player_id"] for p in players]
    dup_ids = sorted({i for i in ids if ids.count(i) > 1})
    _check(checks, "unique_player_id", not dup_ids, f"duplicate player_ids: {dup_ids}")

    names = [p["name"] for p in players]
    dup_names = sorted({nm for nm in names if names.count(nm) > 1})
    _check(checks, "unique_name", not dup_names, f"duplicate names: {dup_names}")

    pct_bad = [
        p["name"]
        for p in players
        if not (0.0 <= p["projection"]["fg_pct"] <= 1.0)
        or not (0.0 <= p["projection"]["ft_pct"] <= 1.0)
    ]
    _check(checks, "pct_bounds", not pct_bad, f"fg_pct/ft_pct outside [0,1]: {pct_bad}")

    games_bad = [p["name"] for p in players if not (0 <= p["projection"]["games"] <= 82)]
    _check(checks, "games_bounds", not games_bad, f"games outside [0,82]: {games_bad}")

    minutes_bad = [p["name"] for p in players if not (0.0 <= p["projection"]["minutes"] <= 48.0)]
    _check(checks, "minutes_bounds", not minutes_bad, f"minutes outside [0,48]: {minutes_bad}")

    stat_bad = [
        p["name"]
        for p in players
        if any(
            not math.isfinite(p["projection"][f]) or p["projection"][f] < 0
            for f in _RAW_STAT_FIELDS
        )
    ]
    _check(
        checks, "stat_non_negative_finite", not stat_bad,
        f"negative/non-finite raw stat values (z-scores/values excluded): {stat_bad}",
    )

    url_bad = [
        p["name"]
        for p in players
        if any(not src.get("url", "").startswith(("http://", "https://")) for src in p.get("sources", []))
    ]
    _check(checks, "sources_have_urls", not url_bad, f"players with a non-http(s) source url: {url_bad}")

    # per-window sanity: each schedule.windows[label] entry's games must fit
    # inside that label's own week count (e.g. "18-20" is 3 weeks -> max 21
    # games); None is always fine (unavailable schedule/window)
    windows_games_bad: list[str] = []
    # score is normally 0-1 (min-max against the league), but schedule.py's
    # "team not in the fetched schedule" fallback (a real 0-game profile, see
    # dataset.py) normalizes against a league set that doesn't include that
    # team, so it CAN fall outside 0-1 in that edge case -- a documented
    # oddity worth flagging, not a hard schema violation
    windows_score_bad: list[str] = []
    for p in players:
        for label, entry in p.get("schedule", {}).get("windows", {}).items():
            start, end = (int(part) for part in label.split("-"))
            max_games = (end - start + 1) * 7
            games = entry.get("playoff_games")
            score = entry.get("playoff_schedule_score")
            if games is not None and not (0 <= games <= max_games):
                windows_games_bad.append(f"{p['name']}[{label}]")
            if score is not None and not (0.0 <= score <= 1.0):
                windows_score_bad.append(f"{p['name']}[{label}]")
    _check(
        checks, "windows_games_bounds", not windows_games_bad,
        f"players/windows with playoff_games out of [0, window_weeks*7]: {windows_games_bad}",
    )
    _check(
        checks, "windows_score_range", not windows_score_bad,
        f"players/windows with playoff_schedule_score outside [0,1]: {windows_score_bad}",
        warn=True,
    )

    # only warns for the specific "schedule fetched but its playoff window has
    # zero games league-wide" case (pipeline.py's D6 no-fabrication override,
    # e.g. a partial/early-release NBA schedule) -- a schedule that never
    # fetched at all is a separate concern already visible via
    # payload["schedule_available"], not re-flagged here
    playoff_window_forced = bool(payload.get("playoff_window_force_unavailable", False))
    _check(
        checks, "playoff_window_coverage", not playoff_window_forced,
        (
            "playoff window force-unavailable: league-wide playoff-window game "
            "total is 0 (partial/early-release NBA schedule -- normal before "
            "the league finalizes later months)"
            if playoff_window_forced
            else "playoff window has real league-wide games, or no schedule was fetched at all"
        ),
        warn=playoff_window_forced,
    )

    # B1: any name in the top 50 of ANY consensus list must resolve to a
    # player somewhere in the pipeline pool -- not just the exported top 200
    # -- else a real, consensus-ranked player (e.g. a returner) silently
    # never made it into the universe at all. Fail-level (not warn): this is
    # exactly the bug class B1 fixed, so a regression here should block, not
    # just get logged.
    top50_pool_missing: list[dict] | None = None
    if store is not None and pool_names is not None:
        normalized_pool = {normalize_name(name) for name in pool_names}
        top50_pool_missing = [
            {"name": name, "source": lst.source.source}
            for lst in store.consensus_lists
            for name in lst.players[:50]
            if normalize_name(name) not in normalized_pool
        ]
        _check(
            checks, "consensus_top50_in_pool", not top50_pool_missing,
            f"top-50 consensus names missing from the pipeline pool: {top50_pool_missing}",
        )

    overall_status = "fail" if any(c["status"] == "fail" for c in checks) else "pass"

    unmatched_consensus_names: list[dict] | None = None
    diff_note = (
        "only reports projected players matched to zero consensus sources; "
        "the reverse (source-list names never matched a projected player) "
        "needs validate_dataset(..., store=...) -- omitted here since no "
        "store was passed."
    )
    if store is not None:
        # normalize_name on both sides mirrors consensus_ranks' own matching
        # rule, so a name flagged here is a genuine miss, not a formatting quirk
        projected_norm_names = {normalize_name(p["name"]) for p in players}
        unmatched_consensus_names = [
            {"name": name, "source": lst.source.source}
            for lst in store.consensus_lists
            for name in lst.players
            if normalize_name(name) not in projected_norm_names
        ]
        diff_note = "covers both directions: store was provided to validate_dataset."

    analysis = {
        "top_rank_disagreements": sorted(
            (
                {"name": p["name"], "rank_difference": p["consensus"]["rank_difference"]}
                for p in players
                if p["consensus"]["rank_difference"] is not None
            ),
            key=lambda d: abs(d["rank_difference"]),
            reverse=True,
        )[:10],
        "missing_consensus": [p["name"] for p in players if p["consensus"]["consensus_rank"] is None],
        "confidence_low": [p["name"] for p in players if p["model"]["confidence_band"] == "LOW"],
        "injury_high": [p["name"] for p in players if p["availability"]["injury_risk_label"] == "high"],
        "consensus_pool_diff": {
            "projected_players_in_no_list": [
                p["name"] for p in players if p["consensus"]["sources_used"] == 0
            ],
            "unmatched_consensus_names": unmatched_consensus_names,
            "note": diff_note,
        },
    }

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "status": overall_status,
        "checks": checks,
        "analysis": analysis,
    }
    _write_report(report_path, report)
    return overall_status == "pass"
