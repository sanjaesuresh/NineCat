"""Import CSV-based per-game stat projections into the warehouse.

Projection sources (e.g. a preseason ranking site) are not the same as
NBA.com's own boxscore averages, so projections get their own table
(PlayerProjection) keyed by (nba_player_id, season, source) rather than
reusing PlayerSeasonAverage. Scraping a live projection source is out of
scope until its terms of use are verified, so CSV import is the only
supported path for now.

CSV header contract (required columns, any order):
    player,team,games,fgm,fga,ftm,fta,tpm,pts,reb,ast,stl,blk,tov

- player: full name as it appears on NBA.com (matched against
  NbaPlayer.full_name -- exact match first, then normalize_name-normalized;
  see the matching rules on import_projections_csv). A row whose name can't
  be matched, or matches 2+ NbaPlayer rows at either stage, is skipped.
- team: NBA abbreviation, informational only -- never used for matching or
  storage.
- games: projected games played for the season (integer).
- fgm, fga, ftm, fta, tpm, pts, reb, ast, stl, blk, tov: per-game projected
  values (floats), matching PlayerSeasonAverage's per-game contract.

A CSV missing any required column is rejected outright (ValueError naming
the missing columns) rather than silently importing a partial row.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.models.warehouse import NbaPlayer, PlayerProjection
from ninecat.warehouse.id_mapping import normalize_name

# required CSV header columns; enforced up front so a malformed source file
# fails fast with a clear message instead of raising deep inside row parsing
_REQUIRED_COLUMNS = (
    "player",
    "team",
    "games",
    "fgm",
    "fga",
    "ftm",
    "fta",
    "tpm",
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
)
# per-game stat columns stored as floats on PlayerProjection
_STAT_FIELDS = ("fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov")


@dataclass(frozen=True)
class ImportResult:
    """Outcome of one import_projections_csv call."""

    imported: int = 0
    unmatched: list[str] = field(default_factory=list)


def import_projections_csv(
    session: Session, file_path: str | Path, source_name: str, season: str
) -> ImportResult:
    """Parse a projections CSV and upsert matched rows into PlayerProjection.

    Matching mirrors id_mapping.map_yahoo_players' exact-then-normalized-then-
    unmatched semantics, but resolves straight to NbaPlayer with no PlayerIdMap
    row: projections are already keyed by NBA name, not a Yahoo player_key that
    needs a persisted yahoo<->nba bridge. Re-importing the same (season, source)
    updates existing rows in place rather than duplicating them.
    """
    with Path(file_path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = set(reader.fieldnames or [])
        missing = [col for col in _REQUIRED_COLUMNS if col not in header]
        if missing:
            raise ValueError(
                f"projections CSV missing required column(s): {', '.join(missing)}"
            )
        rows = list(reader)

    if not rows:
        return ImportResult()

    # load every NbaPlayer once and index by exact + normalized name, rather
    # than a query per row -- cheap at league-roster scale, and lets ambiguity
    # be detected as "2+ entries in a bucket" just like map_yahoo_players
    all_players = session.execute(select(NbaPlayer)).scalars().all()
    by_full_name: dict[str, list[NbaPlayer]] = defaultdict(list)
    by_normalized: dict[str, list[NbaPlayer]] = defaultdict(list)
    for player in all_players:
        by_full_name[player.full_name].append(player)
        by_normalized[normalize_name(player.full_name)].append(player)

    unmatched_names: list[str] = []
    # (csv name, matched NbaPlayer, source row) -- kept together so a later
    # duplicate-player check can report the offending CSV name(s), not just an id
    matched_rows: list[tuple[str, NbaPlayer, dict]] = []

    for row in rows:
        name = row["player"]
        exact_candidates = by_full_name.get(name, [])
        matched_player: NbaPlayer | None = None
        if len(exact_candidates) == 1:
            matched_player = exact_candidates[0]
        elif len(exact_candidates) == 0:
            # only an exact-stage MISS tries normalized; an exact-stage
            # ambiguity (2+ share this exact name) never falls through to a
            # normalized guess -- same rule as map_yahoo_players
            normalized_candidates = by_normalized.get(normalize_name(name), [])
            if len(normalized_candidates) == 1:
                matched_player = normalized_candidates[0]

        if matched_player is None:
            unmatched_names.append(name)
            continue

        matched_rows.append((name, matched_player, row))

    # two CSV rows resolving to the same NbaPlayer (e.g. the same player listed
    # twice, or two name spellings that both match one player) would otherwise
    # reach Postgres as a multi-row ON CONFLICT touching one row twice, which
    # Postgres rejects outright -- catch it here instead and name the player(s)
    # involved, same as the missing-column check, rather than let a cryptic
    # database error surface for user-supplied input
    names_by_player_id: dict[int, list[str]] = defaultdict(list)
    for name, player, _ in matched_rows:
        names_by_player_id[player.id].append(name)
    duplicated_names = sorted(
        {name for names in names_by_player_id.values() if len(names) > 1 for name in names}
    )
    if duplicated_names:
        raise ValueError(
            "projections CSV has multiple rows for the same player: "
            f"{', '.join(duplicated_names)}"
        )

    if not matched_rows:
        return ImportResult(imported=0, unmatched=unmatched_names)

    values = [
        {
            "nba_player_id": player.id,
            "season": season,
            "source": source_name,
            "projected_games": int(float(row["games"])),
            **{stat: float(row[stat]) for stat in _STAT_FIELDS},
        }
        for _, player, row in matched_rows
    ]

    # ON CONFLICT DO UPDATE keyed on (nba_player_id, season, source): re-running
    # an import for the same season/source updates values instead of duplicating
    insert_stmt = pg_insert(PlayerProjection).values(values)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[
            PlayerProjection.nba_player_id,
            PlayerProjection.season,
            PlayerProjection.source,
        ],
        set_={
            "projected_games": insert_stmt.excluded.projected_games,
            **{stat: getattr(insert_stmt.excluded, stat) for stat in _STAT_FIELDS},
            # onupdate=func.now() does NOT fire for ON CONFLICT updates
            # (SQLAlchemy only applies onupdate to ORM-driven UPDATEs), so it
            # must be set explicitly here or synced_at would freeze at
            # first-insert time on every later re-import
            "synced_at": func.now(),
        },
    )
    session.execute(upsert_stmt)

    return ImportResult(imported=len(values), unmatched=unmatched_names)
