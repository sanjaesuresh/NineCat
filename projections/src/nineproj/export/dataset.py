"""Write players_2026_27.json, the D7 interop CSV, and refresh sources.json.

Every number here is read straight off a PipelineResult -- no recomputation,
so the exported dataset is exactly what the pipeline produced (transparency
principle: the export layer only serializes, never derives).
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path

from nineproj.config import Settings
from nineproj.data.nba_stats import provenance
from nineproj.data.schedule import PlayoffProfile
from nineproj.export.pipeline import PipelineResult
from nineproj.research.store import EvidenceStore

# fixed by backend/src/ninecat/warehouse/projections.py's import_projections_csv
# -- any reorder/rename/addition breaks that importer's header contract
_CSV_HEADER = (
    "player", "team", "games", "fgm", "fga", "ftm", "fta", "tpm", "pts",
    "reb", "ast", "stl", "blk", "tov",
)

_TOP_N = 200


def _window_label(window: tuple[int, int]) -> str:
    """"17-19"-style dashboard key for a (start_week, end_week) candidate window."""
    return f"{window[0]}-{window[1]}"


def _player_sources(name: str, store: EvidenceStore) -> list[dict]:
    """Every research SourceRef that touched this player, deduped by url (first wins)."""
    refs = [
        *(note.source for note in store.roles_for(name)),
        *(note.source for note in store.injuries_for(name)),
        *(note.source for note in store.transactions_for(name)),
    ]
    rookie_note = store.rookie_for(name)
    if rookie_note is not None:
        refs.append(rookie_note.source)

    deduped: dict[str, dict] = {}
    for ref in refs:
        deduped.setdefault(
            ref.url,
            {"source": ref.source, "url": ref.url, "retrieved": ref.retrieved, "type": ref.type},
        )
    return list(deduped.values())


def _player_json(pid: str, rank: int, result: PipelineResult) -> dict:
    record = result.records[pid]
    adjusted = result.adjusted[pid]
    availability = result.availabilities[pid]
    value = result.values[pid]
    playoff = result.playoff_values[pid]
    composite = result.composite[pid]
    explanation = result.explanations[pid]
    profile = result.profiles[pid]
    consensus = result.consensus[pid]

    fg_pct = adjusted.fgm / adjusted.fga if adjusted.fga > 0 else 0.0
    ft_pct = adjusted.ftm / adjusted.fta if adjusted.fta > 0 else 0.0
    has_schedule = isinstance(profile, PlayoffProfile)

    # one entry per settings.candidate_playoff_windows option, so the
    # dashboard's dropdown can swap window client-side without a pipeline
    # re-run; the shipped default fields above are guaranteed (by pipeline.py
    # building both off the same window_profiles/window_values) to equal this
    # dict's entry for settings.playoff_window's own window
    windows: dict[str, dict] = {}
    for candidate in result.settings.candidate_playoff_windows:
        window_profile = result.window_profiles[candidate][pid]
        window_value = result.window_values[candidate][pid]
        window_has_schedule = isinstance(window_profile, PlayoffProfile)
        windows[_window_label(candidate)] = {
            "week_games": window_profile.games_by_week if window_has_schedule else None,
            "playoff_games": window_profile.playoff_games if window_has_schedule else None,
            "playoff_b2bs": window_profile.playoff_b2b_count if window_has_schedule else None,
            "playoff_schedule_score": window_profile.playoff_schedule_score if window_has_schedule else None,
            "expected_playoff_games": window_value.expected_playoff_games,
            "playoff_value_z": window_value.playoff_value_z,
        }

    return {
        "rank": rank,
        "player_id": pid,
        "name": record.name,
        "team": record.team,
        "positions": sorted(record.slot_classes),
        "age": int(record.age) if record.age is not None else None,
        "projection": {
            "games": availability.injury_adjusted_games,
            "minutes": adjusted.minutes,
            "points": adjusted.pts,
            "rebounds": adjusted.reb,
            "assists": adjusted.ast,
            "steals": adjusted.stl,
            "blocks": adjusted.blk,
            "three_pm": adjusted.tpm,
            "fg_pct": fg_pct,
            "ft_pct": ft_pct,
            "turnovers": adjusted.tov,
            "fga": adjusted.fga,
            "fta": adjusted.fta,
            "fgm": adjusted.fgm,
            "ftm": adjusted.ftm,
        },
        "fantasy": {
            "per_game_zscores": value.per_game_zscores,
            "per_game_value": value.per_game_value,
            "availability_adjusted_zscores": value.availability_adjusted_zscores,
            "availability_adjusted_value": value.availability_adjusted_value,
            "regular_season_value": playoff.regular_season_z,
            "playoff_value": playoff.playoff_value,
            "combined_value": playoff.combined_value,
            "final_score": composite.final_score,
            "punt_values": value.punt_values,
            "scarcity_score": value.scarcity_score,
        },
        "availability": {
            "raw_projected_games": availability.raw_projected_games,
            "injury_adjusted_games": availability.injury_adjusted_games,
            "injury_risk_score": availability.injury_risk_score,
            "injury_risk_label": availability.injury_risk_label,
            "availability_probability": availability.availability_probability,
        },
        "role": {
            "role_change_score": adjusted.role_change.score,
            "direction": adjusted.role_change.direction,
            "minutes_delta": adjusted.role_change.minutes_delta,
            "usage_delta": adjusted.role_change.usage_delta,
            "minutes_projection": adjusted.minutes,
            # no evidence source in this pipeline distinguishes projected
            # starters from bench players -- null rather than guessed
            "starter_probability": None,
            "team_changed": result.team_changed[pid],
            "pace_multiplier": adjusted.pace_multiplier,
        },
        "schedule": {
            "week_games": profile.games_by_week if has_schedule else None,
            "playoff_games": profile.playoff_games if has_schedule else None,
            "playoff_b2bs": profile.playoff_b2b_count if has_schedule else None,
            "playoff_schedule_score": profile.playoff_schedule_score if has_schedule else None,
            # already null exactly when unavailable (own D6 branch in playoffs.py)
            "expected_playoff_games": playoff.expected_playoff_games,
            "windows": windows,
        },
        "consensus": {
            "consensus_rank": consensus.consensus_rank if consensus else None,
            "sources_used": consensus.sources_used if consensus else 0,
            "rank_variance": consensus.rank_variance if consensus else None,
            "per_source": consensus.per_source if consensus else {},
            "rank_difference": composite.disagreement.rank_difference,
            "flag": composite.disagreement.flag,
        },
        "model": {
            "model_rank": composite.model_rank,
            "final_rank": rank,
            "confidence": composite.confidence,
            "confidence_band": composite.confidence_band,
            "component_scores": composite.component_scores,
            "component_contributions": composite.component_contributions,
        },
        "analysis": {
            "strengths": explanation.strengths,
            "risks": explanation.risks,
            "explanation": explanation.paragraph,
        },
        "sources": _player_sources(record.name, result.store),
    }


def _refresh_sources(sources_path: Path) -> None:
    """Merge nba_stats' accumulated endpoint provenance into the curated sources.json.

    nba_stats.provenance() entries have no "url" (stats.nba.com's API has none
    to cite), so they're kept in their own key rather than forced into the
    hand-curated "sources" list's url-required shape.
    """
    existing: dict = json.loads(sources_path.read_text()) if sources_path.exists() else {}

    endpoints = existing.get("nba_stats_endpoints", [])
    seen = {(e.get("endpoint"), e.get("season")) for e in endpoints}
    for entry in provenance():
        key = (entry["endpoint"], entry["season"])
        if key not in seen:
            endpoints.append(entry)
            seen.add(key)

    existing["nba_stats_endpoints"] = endpoints
    existing["generated"] = date.today().isoformat()  # stamped on every refresh

    sources_path.parent.mkdir(parents=True, exist_ok=True)
    sources_path.write_text(json.dumps(existing, indent=2))


def build_dataset(
    result: PipelineResult,
    settings: Settings,
    output_path: str | Path,
    csv_path: str | Path,
    sources_path: str | Path,
) -> None:
    """Write players_2026_27.json, the D7 CSV, and refresh sources.json from one PipelineResult."""
    # compute_composite's final_rank is already dense 1..pool_size, but the
    # top-N slice is re-ranked explicitly here rather than trusted, so a
    # shortfall pool (<200) still comes out contiguous 1..N by construction
    ordered_pids = sorted(result.composite, key=lambda pid: result.composite[pid].final_rank)
    top_pids = ordered_pids[:_TOP_N]

    players = [_player_json(pid, rank, result) for rank, pid in enumerate(top_pids, start=1)]

    payload = {
        "season": settings.season,
        "projection_date": result.projection_date,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "settings": settings.model_dump(),
        "schedule_available": result.schedule_available,
        # distinguishes "no schedule fetched at all" from "schedule fetched
        # but its playoff window has zero games league-wide" (partial/
        # early-release schedule) -- validate.py's playoff_window_coverage
        # check only warns on the latter
        "playoff_window_force_unavailable": result.playoff_window_force_unavailable,
        # derived from settings, not hardcoded -- stays correct if the
        # candidate list or the primary playoff_window ever changes
        "candidate_windows": [_window_label(w) for w in settings.candidate_playoff_windows],
        "default_window": _window_label((settings.playoff_window.start_week, settings.playoff_window.end_week)),
        "players": players,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))

    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(_CSV_HEADER)
        for pid in top_pids:
            record = result.records[pid]
            adjusted = result.adjusted[pid]
            availability = result.availabilities[pid]
            writer.writerow(
                [
                    record.name, record.team, availability.injury_adjusted_games,
                    adjusted.fgm, adjusted.fga, adjusted.ftm, adjusted.fta, adjusted.tpm,
                    adjusted.pts, adjusted.reb, adjusted.ast, adjusted.stl, adjusted.blk,
                    adjusted.tov,
                ]
            )

    _refresh_sources(Path(sources_path))
