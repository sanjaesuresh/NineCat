"""Sync NbaPlayer.position from nba_api's PlayerIndex endpoint.

Separate from player_stats.sync_player_averages on purpose: LeagueDashPlayerStats
(the averages source) carries no position column at all, and PlayerIndex has a
different response shape and update cadence (roster/position churn, not nightly
per-game stat recalculation). Keeping the two syncs apart means a PlayerIndex
outage or shape change can't break the averages sync the draft engine depends on
every night -- see jobs/scheduler.nightly_warehouse_sync, which runs this AFTER
the averages sync and treats a failure here as non-fatal.

Mirrors player_stats.py's shape: a normalized row format any fetcher (live
nba_api or a test fixture) can produce, injected so tests never hit the network.
Unlike sync_player_averages, this sync never creates NbaPlayer rows -- the
averages sync owns row creation; a position for an nba_person_id we don't
already know about is simply skipped.

Same failure class as the T1 review finding that added the coalesce to
sync_player_averages: a blank/missing position in a payload row PRESERVES
whatever is already stored (None or a real value) rather than nulling it --
a transient blank on one nightly PlayerIndex pull must never be trusted over
a real position a prior sync already recorded.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, select, update
from sqlalchemy.orm import Session

from ninecat.models.warehouse import NbaPlayer

# a normalized position row, shaped the same whether it came from nba_api or a
# test fixture: {nba_person_id, position (optional -- PlayerIndex's short-form
# abbreviation string, e.g. "G"/"F-C"/"G-F"; may be absent, blank, or None, all
# of which are stored as NULL)}
PlayerPositionRow = Mapping[str, Any]
Fetcher = Callable[[str], Iterable[PlayerPositionRow]]


@dataclass(frozen=True)
class PositionSyncResult:
    """Outcome of one sync_player_positions call."""

    matched: int = 0
    skipped: int = 0


def _default_fetcher(season: str) -> list[PlayerPositionRow]:
    """Pull the current season's player positions from nba_api's PlayerIndex.

    Imported lazily so importing this module (or running the test suite, which
    always injects a fetcher) never requires nba_api or network access.

    Verified live against the installed nba_api package (season "2025-26"):
    PlayerIndex's POSITION column returns nba_api's SHORT-form abbreviation
    vocabulary -- "G", "F", "C", and hyphenated combos like "G-F"/"C-F"/"F-C"/
    "F-G" -- never the long forms ("Guard"/"Forward"/"Center"). That matters:
    engine/positions.slot_classes deliberately maps short forms to a WIDER set
    of Yahoo slot classes than the more specific "PG"/"SG"/etc tokens, so this
    endpoint's short-form vocabulary is exactly what that mapping expects.
    CommonAllPlayers (the older alternative) carries no position column at all.
    """
    from nba_api.stats.endpoints import playerindex

    response = playerindex.PlayerIndex(season=season)
    payload = response.player_index.get_dict()
    headers: list[str] = payload["headers"]

    def col(row: list, name: str) -> object:
        return row[headers.index(name)]

    normalized: list[PlayerPositionRow] = []
    for row in payload["data"]:
        normalized.append(
            {
                "nba_person_id": int(col(row, "PERSON_ID")),
                "position": col(row, "POSITION"),
            }
        )
    return normalized


def sync_player_positions(
    session: Session, season: str, fetcher: Fetcher | None = None
) -> PositionSyncResult:
    """Fetch a season's player positions and upsert them onto existing NbaPlayer rows.

    `fetcher` defaults to a live nba_api call; tests inject a fixture-backed
    callable instead so the suite never hits the network. Matches rows by
    nba_person_id (NbaPlayer's natural key); an nba_person_id with no existing
    NbaPlayer row is skipped, never inserted -- sync_player_averages owns row
    creation. A row with a blank/missing position is still counted matched
    (the player was found), but its write is skipped entirely so the existing
    stored position (real value or NULL) is left alone. Returns counts of
    matched vs skipped rows.
    """
    fetch = fetcher or _default_fetcher
    fetched_rows = list(fetch(season))
    if not fetched_rows:
        return PositionSyncResult()

    # dedupe by nba_person_id first (last occurrence wins), same pattern as
    # sync_player_averages: a fetcher could return the same player twice in
    # one batch, and a single UPDATE..executemany hitting the same row twice
    # would just be wasted work, but this keeps the matched/skipped counts honest
    rows_by_person_id: dict[int, PlayerPositionRow] = {}
    for row in fetched_rows:
        rows_by_person_id[row["nba_person_id"]] = row
    rows = list(rows_by_person_id.values())

    person_ids = [row["nba_person_id"] for row in rows]
    existing_person_ids = set(
        session.execute(
            select(NbaPlayer.nba_person_id).where(NbaPlayer.nba_person_id.in_(person_ids))
        ).scalars()
    )

    matched_rows = [row for row in rows if row["nba_person_id"] in existing_person_ids]
    skipped = len(rows) - len(matched_rows)

    # coalesce, not a bare overwrite: a blank/whitespace-only or missing
    # position must never null out (or clobber) whatever is already stored --
    # only a row that actually carries a real position gets written at all
    writable_rows = [
        {
            "person_id": row["nba_person_id"],
            "new_position": (row.get("position") or "").strip(),
        }
        for row in matched_rows
        if (row.get("position") or "").strip()
    ]

    if writable_rows:
        # plain UPDATE, not an upsert: this sync never creates NbaPlayer rows,
        # so ON CONFLICT DO UPDATE (which requires an INSERT) is the wrong tool
        # here -- bindparam + executemany-style params updates all matched
        # rows in one statement while still only touching existing rows.
        # Built against NbaPlayer.__table__ (Core), not the NbaPlayer class
        # (ORM): SQLAlchemy 2.0 auto-detects an executemany update() against
        # a mapped class as an "ORM bulk UPDATE by primary key", which then
        # demands the primary key (id) in every params dict -- we only have
        # nba_person_id, the natural key this sync actually matches on
        update_stmt = (
            update(NbaPlayer.__table__)
            .where(NbaPlayer.nba_person_id == bindparam("person_id"))
            .values(position=bindparam("new_position"))
        )
        session.execute(update_stmt, writable_rows)

    return PositionSyncResult(matched=len(matched_rows), skipped=skipped)
