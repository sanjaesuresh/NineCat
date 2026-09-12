from datetime import date

from sqlalchemy import select

from ninecat.models import League, LeagueFreeAgent, NbaPlayer, PlayerIdMap
from ninecat.sync.free_agents import FreeAgentSyncResult, sync_league_free_agents
from ninecat.yahoo.parsers import FreeAgentEntry

LEAGUE_KEY = "466.l.1"


class _StubClient:
    """Stands in for YahooClient: returns canned FreeAgentEntry rows for one
    league key, no gateway/network involved."""

    def __init__(self, entries: list[FreeAgentEntry] | None = None):
        self._entries = entries or []

    def get_league_players(self, league_key: str, status: str = "A") -> list[FreeAgentEntry]:
        assert league_key == LEAGUE_KEY
        assert status == "A"
        return self._entries


def _entry(key: str, name: str, status: str = "FA", waiver_date: date | None = None) -> FreeAgentEntry:
    return FreeAgentEntry(
        player_key=key, name=name, status=status, waiver_date=waiver_date, eligible_positions=["PG"]
    )


def _make_league(session, key: str = LEAGUE_KEY) -> League:
    league = League(
        yahoo_league_key=key, name="stub", season=2026, num_teams=2, scoring_type="head", settings_json={}
    )
    session.add(league)
    session.flush()
    return league


def test_sync_writes_a_row_per_mapped_free_agent(db_session):
    db_session.add_all(
        [
            NbaPlayer(nba_person_id=1, full_name="Free Agent One"),
            NbaPlayer(nba_person_id=2, full_name="Free Agent Two"),
        ]
    )
    db_session.flush()
    league = _make_league(db_session)
    client = _StubClient(
        [_entry("466.p.1", "Free Agent One"), _entry("466.p.2", "Free Agent Two", status="W", waiver_date=date(2026, 9, 20))]
    )

    result = sync_league_free_agents(db_session, client, league)
    db_session.flush()

    assert result == FreeAgentSyncResult(fetched=2, wrote=2, unmapped=0)
    rows = db_session.execute(
        select(LeagueFreeAgent).where(LeagueFreeAgent.league_id == league.id)
    ).scalars().all()
    assert len(rows) == 2
    by_status = {r.status for r in rows}
    assert by_status == {"FA", "W"}
    waiver_row = next(r for r in rows if r.status == "W")
    assert waiver_row.waiver_date == date(2026, 9, 20)


def test_sync_counts_unmapped_without_writing_a_row_for_them(db_session):
    db_session.add(NbaPlayer(nba_person_id=3, full_name="Free Agent One"))
    db_session.flush()
    league = _make_league(db_session)
    client = _StubClient(
        [_entry("466.p.1", "Free Agent One"), _entry("466.p.9", "Nobody Nba Player Knows")]
    )

    result = sync_league_free_agents(db_session, client, league)
    db_session.flush()

    # surfaced in the return value, not silently dropped -- and PlayerIdMap
    # still records the unmatched key for a human to fix up later
    assert result == FreeAgentSyncResult(fetched=2, wrote=1, unmapped=1)
    rows = db_session.execute(
        select(LeagueFreeAgent).where(LeagueFreeAgent.league_id == league.id)
    ).scalars().all()
    assert len(rows) == 1
    unmatched = db_session.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "466.p.9")
    ).scalar_one()
    assert unmatched.match_method == "unmatched"
    assert unmatched.nba_player_id is None


def test_rerun_replaces_the_snapshot_exactly(db_session):
    """A player claimed off waivers between syncs must disappear from the
    snapshot -- there is no upsert key to diff it away by, so the whole set
    is replaced (same pattern/reasoning as RosterSlot's sync)."""
    db_session.add_all(
        [
            NbaPlayer(nba_person_id=10, full_name="Still Available"),
            NbaPlayer(nba_person_id=11, full_name="Got Claimed"),
            NbaPlayer(nba_person_id=12, full_name="New Cut"),
        ]
    )
    db_session.flush()
    league = _make_league(db_session)
    first_client = _StubClient(
        [_entry("466.p.10", "Still Available"), _entry("466.p.11", "Got Claimed")]
    )
    sync_league_free_agents(db_session, first_client, league)
    db_session.flush()
    before = db_session.execute(
        select(LeagueFreeAgent).where(LeagueFreeAgent.league_id == league.id)
    ).scalars().all()
    assert {r.nba_player_id for r in before} == {
        p.id for p in db_session.execute(
            select(NbaPlayer).where(NbaPlayer.full_name.in_(["Still Available", "Got Claimed"]))
        ).scalars().all()
    }

    # "Got Claimed" no longer available; "New Cut" newly hit the wire
    second_client = _StubClient(
        [_entry("466.p.10", "Still Available"), _entry("466.p.12", "New Cut")]
    )
    result = sync_league_free_agents(db_session, second_client, league)
    db_session.flush()
    db_session.expire_all()

    after = db_session.execute(
        select(LeagueFreeAgent).where(LeagueFreeAgent.league_id == league.id)
    ).scalars().all()
    names = {
        db_session.get(NbaPlayer, r.nba_player_id).full_name for r in after
    }
    assert names == {"Still Available", "New Cut"}
    assert "Got Claimed" not in names
    assert result.wrote == 2
    # no duplicates left behind by the replace
    assert len(after) == len(set(r.nba_player_id for r in after))


def test_sync_with_no_free_agents_clears_a_prior_snapshot(db_session):
    db_session.add(NbaPlayer(nba_person_id=20, full_name="Solo Agent"))
    db_session.flush()
    league = _make_league(db_session)
    sync_league_free_agents(db_session, _StubClient([_entry("466.p.20", "Solo Agent")]), league)
    db_session.flush()

    result = sync_league_free_agents(db_session, _StubClient([]), league)
    db_session.flush()

    assert result == FreeAgentSyncResult(fetched=0, wrote=0, unmapped=0)
    rows = db_session.execute(
        select(LeagueFreeAgent).where(LeagueFreeAgent.league_id == league.id)
    ).scalars().all()
    assert rows == []


def test_sync_dedupes_two_yahoo_keys_mapped_to_the_same_nba_player(db_session):
    # a bad name match (or a genuine yahoo dup across pages) resolving two
    # different yahoo keys to the same nba_player_id must not violate the
    # (league_id, nba_player_id) unique constraint
    db_session.add(NbaPlayer(nba_person_id=30, full_name="Duplicate Target"))
    db_session.flush()
    league = _make_league(db_session)
    client = _StubClient(
        [_entry("466.p.30", "Duplicate Target"), _entry("466.p.31", "Duplicate Target")]
    )

    result = sync_league_free_agents(db_session, client, league)
    db_session.flush()

    assert result.wrote == 1
    rows = db_session.execute(
        select(LeagueFreeAgent).where(LeagueFreeAgent.league_id == league.id)
    ).scalars().all()
    assert len(rows) == 1
