import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from ninecat.db import get_engine
from ninecat.models import NbaPlayer, NbaTeam, PlayerSeasonAverage
from ninecat.warehouse.player_stats import sync_player_averages

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nba" / "sample_player_averages.json"

CURRY_PERSON_ID = 201939
DONCIC_PERSON_ID = 1629029
JJJ_PERSON_ID = 1630163

# the exact 3 players sample_player_averages.json produces -- scoping queries to
# these natural keys (rather than a bare select(NbaPlayer)/select(PlayerSeasonAverage))
# lets these tests prove "upserts, never duplicates" even when the shared dev database
# already carries unrelated committed rows (e.g. from a real dev-login/e2e run)
_FIXTURE_PERSON_IDS = [CURRY_PERSON_ID, DONCIC_PERSON_ID, JJJ_PERSON_ID]

BOS_NBA_TEAM_ID = 1610612738


def _fixture_fetcher(season: str) -> list[dict]:
    """Test fetcher standing in for the real nba_api call: reads the hand-built fixture."""
    return json.loads(FIXTURE_PATH.read_text())


def test_sync_player_averages_upserts_players_and_averages(db_session):
    # a team must already exist for the fixture's team-linked player to resolve --
    # get-or-create rather than a bare insert: BOS_NBA_TEAM_ID is a real NBA.com
    # natural key that can already be present in the shared dev database from an
    # unrelated committed dev-login/e2e seed, and a raw insert would collide on
    # the nba_team_id unique constraint
    existing_team = db_session.execute(
        select(NbaTeam).where(NbaTeam.nba_team_id == BOS_NBA_TEAM_ID)
    ).scalar_one_or_none()
    if existing_team is None:
        db_session.add(
            NbaTeam(nba_team_id=BOS_NBA_TEAM_ID, name="Boston Celtics", abbreviation="BOS")
        )
        db_session.flush()

    count = sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    assert count == 3
    players = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id.in_(_FIXTURE_PERSON_IDS))
    ).scalars().all()
    averages = db_session.execute(
        select(PlayerSeasonAverage).where(
            PlayerSeasonAverage.nba_player_id.in_([p.id for p in players])
        )
    ).scalars().all()
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
    players = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id.in_(_FIXTURE_PERSON_IDS))
    ).scalars().all()
    averages = db_session.execute(
        select(PlayerSeasonAverage).where(
            PlayerSeasonAverage.nba_player_id.in_([p.id for p in players])
        )
    ).scalars().all()
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

    players = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id.in_(_FIXTURE_PERSON_IDS))
    ).scalars().all()
    averages = db_session.execute(
        select(PlayerSeasonAverage).where(
            PlayerSeasonAverage.nba_player_id.in_([p.id for p in players])
        )
    ).scalars().all()
    assert len(players) == 3
    assert len(averages) == 3

    curry = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == CURRY_PERSON_ID)
    ).scalar_one()
    average = db_session.execute(
        select(PlayerSeasonAverage).where(PlayerSeasonAverage.nba_player_id == curry.id)
    ).scalar_one()
    assert average.pts == 30.0


def test_sync_player_averages_persists_position_when_present(db_session):
    sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    curry = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == CURRY_PERSON_ID)
    ).scalar_one()
    assert curry.position == "Guard"


def test_sync_player_averages_stores_none_for_blank_or_missing_position(db_session):
    # doncic's fixture row has an explicit blank "" position; jjj's row omits
    # the key entirely -- both must land as None, never crash or store ""
    sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    doncic = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == DONCIC_PERSON_ID)
    ).scalar_one()
    jjj = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == JJJ_PERSON_ID)
    ).scalar_one()
    assert doncic.position is None
    assert jjj.position is None


def test_sync_player_averages_rerun_with_changed_position_updates_in_place(db_session):
    sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    def _repositioned_fetcher(season: str) -> list[dict]:
        rows = json.loads(FIXTURE_PATH.read_text())
        for row in rows:
            if row["nba_person_id"] == CURRY_PERSON_ID:
                row["position"] = "PG"
        return rows

    sync_player_averages(db_session, season="2025-26", fetcher=_repositioned_fetcher)
    db_session.flush()
    db_session.expire_all()

    curry = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == CURRY_PERSON_ID)
    ).scalar_one()
    assert curry.position == "PG"


def test_sync_player_averages_position_blind_resync_preserves_existing_position(db_session):
    # the nightly job's live fetcher never supplies a position (LeagueDashPlayerStats
    # has no position column) -- a re-sync from a position-blind fetcher must not
    # NULL out a position a prior sync/backfill already stored
    sync_player_averages(db_session, season="2025-26", fetcher=_fixture_fetcher)
    db_session.flush()

    def _position_blind_fetcher(season: str) -> list[dict]:
        rows = json.loads(FIXTURE_PATH.read_text())
        for row in rows:
            row.pop("position", None)
        return rows

    sync_player_averages(db_session, season="2025-26", fetcher=_position_blind_fetcher)
    db_session.flush()
    db_session.expire_all()

    curry = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == CURRY_PERSON_ID)
    ).scalar_one()
    assert curry.position == "Guard"


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
    players = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id.in_(_FIXTURE_PERSON_IDS))
    ).scalars().all()
    averages = db_session.execute(
        select(PlayerSeasonAverage).where(
            PlayerSeasonAverage.nba_player_id.in_([p.id for p in players])
        )
    ).scalars().all()
    assert len(players) == 3
    assert len(averages) == 3


# --- migration ---

BACKEND_DIR = Path(__file__).resolve().parents[1]
PRIOR_HEAD = "f7372f04c6a5"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_migration_upgrade_downgrade_upgrade_is_clean_with_single_head():
    # skip (not fail) on a machine/CI without postgres up, matching db_session's
    # own skip behavior elsewhere in this suite
    try:
        get_engine().connect().close()
    except OperationalError as exc:
        pytest.skip(f"Postgres unreachable: {exc}")

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1

    command.downgrade(cfg, PRIOR_HEAD)
    command.upgrade(cfg, "head")
