import json
from pathlib import Path

from sqlalchemy import select

from ninecat.models import NbaPlayer
from ninecat.warehouse.player_positions import PositionSyncResult, sync_player_positions

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nba" / "sample_player_positions.json"

CURRY_PERSON_ID = 201939
DONCIC_PERSON_ID = 1629029
JJJ_PERSON_ID = 1630163
UNKNOWN_PERSON_ID = 999999999


def _fixture_fetcher(season: str) -> list[dict]:
    """Test fetcher standing in for the real nba_api PlayerIndex call."""
    return json.loads(FIXTURE_PATH.read_text())


def _seed_known_players(db_session) -> None:
    # sync_player_positions never creates rows -- the fixture's Curry/Doncic/JJJ
    # rows must already exist for the "matched" path to have anything to update
    db_session.add_all(
        [
            NbaPlayer(nba_person_id=CURRY_PERSON_ID, full_name="Stephen Curry"),
            NbaPlayer(nba_person_id=DONCIC_PERSON_ID, full_name="Luka Doncic"),
            NbaPlayer(nba_person_id=JJJ_PERSON_ID, full_name="Jaren Jackson Jr"),
        ]
    )
    db_session.flush()


def test_sync_player_positions_persists_position_onto_existing_player(db_session):
    _seed_known_players(db_session)

    result = sync_player_positions(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    curry = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == CURRY_PERSON_ID)
    ).scalar_one()
    assert curry.position == "G"
    assert result == PositionSyncResult(matched=3, skipped=1)


def test_sync_player_positions_skips_unknown_person_id_without_creating(db_session):
    _seed_known_players(db_session)

    sync_player_positions(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    unknown = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == UNKNOWN_PERSON_ID)
    ).scalar_one_or_none()
    assert unknown is None


def test_sync_player_positions_blank_position_preserves_existing_stored_position(db_session):
    # doncic's fixture row has an explicit blank "" position -- a transient
    # blank on one pull must never overwrite a real position a prior
    # sync/backfill already recorded (same failure class as the T1 coalesce)
    _seed_known_players(db_session)
    doncic = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == DONCIC_PERSON_ID)
    ).scalar_one()
    doncic.position = "PG"
    db_session.flush()

    result = sync_player_positions(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()
    db_session.expire_all()

    doncic = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == DONCIC_PERSON_ID)
    ).scalar_one()
    assert doncic.position == "PG"
    # still counted matched -- the player WAS found, the write was just skipped
    assert result.matched == 3


def test_sync_player_positions_missing_position_on_never_set_player_stays_none(db_session):
    # jjj's fixture row omits the "position" key entirely, and jjj was never
    # given a position -- must land as None, never crash or store ""
    _seed_known_players(db_session)

    sync_player_positions(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    jjj = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == JJJ_PERSON_ID)
    ).scalar_one()
    assert jjj.position is None


def test_sync_player_positions_is_idempotent_on_rerun(db_session):
    _seed_known_players(db_session)

    sync_player_positions(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()
    result = sync_player_positions(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    assert result == PositionSyncResult(matched=3, skipped=1)
    players = db_session.execute(select(NbaPlayer)).scalars().all()
    # still exactly the 3 seeded players -- no duplicates, unknown id never created
    assert len(players) == 3


def test_sync_player_positions_rerun_with_changed_position_updates_in_place(db_session):
    _seed_known_players(db_session)
    sync_player_positions(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    def _repositioned_fetcher(season: str) -> list[dict]:
        rows = json.loads(FIXTURE_PATH.read_text())
        for row in rows:
            if row["nba_person_id"] == CURRY_PERSON_ID:
                row["position"] = "G-F"
        return rows

    sync_player_positions(db_session, season="2025-26", fetcher=_repositioned_fetcher)
    db_session.flush()
    db_session.expire_all()

    curry = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == CURRY_PERSON_ID)
    ).scalar_one()
    assert curry.position == "G-F"


def test_sync_player_positions_dedupes_duplicate_person_id_in_one_batch(db_session):
    # a fetcher could return the same player twice in one page/batch; the
    # matched/skipped counts must reflect the deduped set, not the raw fetch
    _seed_known_players(db_session)

    def _dup_fetcher(season: str) -> list[dict]:
        rows = json.loads(FIXTURE_PATH.read_text())
        rows.append(dict(rows[0]))
        return rows

    result = sync_player_positions(db_session, season="2025-26", fetcher=_dup_fetcher)
    db_session.flush()

    assert result == PositionSyncResult(matched=3, skipped=1)


def test_sync_player_positions_empty_fetch_returns_zero_result(db_session):
    _seed_known_players(db_session)

    result = sync_player_positions(db_session, season="2025-26", fetcher=lambda season: [])

    assert result == PositionSyncResult(matched=0, skipped=0)
