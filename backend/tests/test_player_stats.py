import json
from pathlib import Path

from sqlalchemy import select

from ninecat.models import NbaPlayer, NbaTeam, PlayerSeasonAverage
from ninecat.warehouse.player_stats import sync_player_averages

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nba" / "sample_player_averages.json"

CURRY_PERSON_ID = 201939
DONCIC_PERSON_ID = 1629029
JJJ_PERSON_ID = 1630163

BOS_NBA_TEAM_ID = 1610612738


def _fixture_fetcher(season: str) -> list[dict]:
    """Test fetcher standing in for the real nba_api call: reads the hand-built fixture."""
    return json.loads(FIXTURE_PATH.read_text())


def test_sync_player_averages_upserts_players_and_averages(db_session):
    # a team must already exist for the fixture's team-linked player to resolve
    db_session.add(
        NbaTeam(nba_team_id=BOS_NBA_TEAM_ID, name="Boston Celtics", abbreviation="BOS")
    )
    db_session.flush()

    count = sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    assert count == 3
    players = db_session.execute(select(NbaPlayer)).scalars().all()
    averages = db_session.execute(select(PlayerSeasonAverage)).scalars().all()
    assert len(players) == 3
    assert len(averages) == 3

    curry = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == CURRY_PERSON_ID)
    ).scalar_one()
    assert curry.full_name == "Stephen Curry"
    assert curry.nba_team_id is not None  # resolved via the pre-seeded BOS team
    assert curry.is_active is True


def test_sync_player_averages_leaves_unresolvable_team_null(db_session):
    # BOS team intentionally not pre-seeded here, and JJJ's fixture team id
    # (9999999) is never a real synced team either way
    sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    jjj = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == JJJ_PERSON_ID)
    ).scalar_one()
    assert jjj.nba_team_id is None

    free_agent = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == DONCIC_PERSON_ID)
    ).scalar_one()
    assert free_agent.nba_team_id is None


def test_sync_player_averages_derives_fg_pct_and_stores_tov_and_games_played(db_session):
    sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    curry = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == CURRY_PERSON_ID)
    ).scalar_one()
    average = db_session.execute(
        select(PlayerSeasonAverage).where(PlayerSeasonAverage.nba_player_id == curry.id)
    ).scalar_one()

    assert average.season == "2025-26"
    assert average.games_played == 55
    assert average.tov == 2.8
    # FG% must be derivable from makes/attempts rather than stored as a bare percentage
    fg_pct = average.fgm / average.fga
    assert round(fg_pct, 3) == round(9.5 / 19.8, 3)


def test_sync_player_averages_is_idempotent_on_rerun(db_session):
    sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()
    count = sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    assert count == 3
    players = db_session.execute(select(NbaPlayer)).scalars().all()
    averages = db_session.execute(select(PlayerSeasonAverage)).scalars().all()
    assert len(players) == 3
    assert len(averages) == 3


def test_sync_player_averages_rerun_with_changed_value_updates_in_place(db_session):
    # unmutated fixture equal-row rerun (above) would pass even under an
    # ON CONFLICT DO NOTHING upsert; this exercises the DO UPDATE branch
    # specifically by changing one player's pts on the second sync and
    # asserting the existing row is updated rather than left stale/duplicated
    sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    def _mutated_fetcher(season: str) -> list[dict]:
        rows = json.loads(FIXTURE_PATH.read_text())
        for row in rows:
            if row["nba_person_id"] == CURRY_PERSON_ID:
                row["pts"] = 30.0
        return rows

    sync_player_averages(db_session, season="2025-26", fetcher=_mutated_fetcher)
    db_session.flush()
    # expire_all forces the next reads through postgres rather than the
    # session's identity map, so this actually proves the row was updated
    db_session.expire_all()

    players = db_session.execute(select(NbaPlayer)).scalars().all()
    averages = db_session.execute(select(PlayerSeasonAverage)).scalars().all()
    assert len(players) == 3
    assert len(averages) == 3

    curry = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == CURRY_PERSON_ID)
    ).scalar_one()
    average = db_session.execute(
        select(PlayerSeasonAverage).where(PlayerSeasonAverage.nba_player_id == curry.id)
    ).scalar_one()
    assert average.pts == 30.0


def test_sync_player_averages_dedupes_duplicate_person_id_in_one_batch(db_session):
    # a fetcher could return the same player twice in one page/batch; without
    # dedupe, a single multi-row ON CONFLICT DO UPDATE hitting the same
    # target row twice in one statement is rejected outright by postgres
    def _dup_fetcher(season: str) -> list[dict]:
        rows = json.loads(FIXTURE_PATH.read_text())
        rows.append(dict(rows[0]))
        return rows

    count = sync_player_averages(db_session, season="2025-26", fetcher=_dup_fetcher)
    db_session.flush()

    assert count == 3
    players = db_session.execute(select(NbaPlayer)).scalars().all()
    averages = db_session.execute(select(PlayerSeasonAverage)).scalars().all()
    assert len(players) == 3
    assert len(averages) == 3
