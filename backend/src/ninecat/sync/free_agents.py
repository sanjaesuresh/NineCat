"""Syncs Yahoo's league free-agent/waiver pool into a per-league snapshot.

Full delete-then-insert on every sync -- the same pattern (and the same
reason) sync/league_sync.py uses for RosterSlot: a player claimed off waivers
since the last sync has no upsert key to diff against, so replacing the whole
snapshot is no more work than diffing and is simplest to get right.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ninecat.models import League, LeagueFreeAgent, PlayerIdMap
from ninecat.warehouse.id_mapping import map_yahoo_players
from ninecat.yahoo.parsers import FreeAgentEntry


class _ClientLike(Protocol):
    """The slice of YahooClient this module needs; a test double can satisfy
    this without going through a gateway."""

    def get_league_players(self, league_key: str, status: str = "A") -> list[FreeAgentEntry]: ...


@dataclass(frozen=True)
class FreeAgentSyncResult:
    """One sync_league_free_agents call's outcome."""

    fetched: int
    wrote: int
    unmapped: int


def sync_league_free_agents(
    session: Session, client: _ClientLike, league: League
) -> FreeAgentSyncResult:
    """Replace `league`'s free-agent snapshot with what Yahoo reports right now.

    Unmapped free agents (no resolvable PlayerIdMap link) are counted and
    returned rather than silently dropped -- callers (the nightly step, the
    on-demand refresh endpoint) surface this count. The snapshot itself can
    only ever hold resolvable nba_player_id rows, since there's nothing else
    to key a row on.
    """
    entries = client.get_league_players(league.yahoo_league_key)

    # always replace, even on an empty fetch (a real "zero free agents" state,
    # or a transient empty page) -- an empty snapshot is honest; a stale one
    # from a prior sync pretending to still be current is not
    session.execute(delete(LeagueFreeAgent).where(LeagueFreeAgent.league_id == league.id))
    if not entries:
        session.flush()
        return FreeAgentSyncResult(fetched=0, wrote=0, unmapped=0)

    # dev-pool-blind by inheritance: map_yahoo_players never matches a real
    # yahoo key onto a seeded dev player, so a real league's snapshot can
    # never end up pointing at fake rows
    map_yahoo_players(session, entries)
    session.flush()

    nba_player_id_by_key = {
        row.yahoo_player_key: row.nba_player_id
        for row in session.execute(
            select(PlayerIdMap).where(
                PlayerIdMap.yahoo_player_key.in_([e.player_key for e in entries])
            )
        )
        .scalars()
        .all()
    }

    wrote = 0
    unmapped = 0
    written_player_ids: set[int] = set()
    for entry in entries:
        nba_player_id = nba_player_id_by_key.get(entry.player_key)
        if nba_player_id is None:
            unmapped += 1
            continue
        if nba_player_id in written_player_ids:
            # two yahoo player_keys resolving to the same nba_player_id (a bad
            # name match, or a genuine dup across pages) would otherwise
            # violate the (league_id, nba_player_id) unique constraint
            continue
        written_player_ids.add(nba_player_id)
        session.add(
            LeagueFreeAgent(
                league_id=league.id,
                nba_player_id=nba_player_id,
                status=entry.status,
                waiver_date=entry.waiver_date,
            )
        )
        wrote += 1

    session.flush()
    return FreeAgentSyncResult(fetched=len(entries), wrote=wrote, unmapped=unmapped)
