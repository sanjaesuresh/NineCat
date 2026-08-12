import csv
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from ninecat.db import get_engine
from ninecat.models import NbaPlayer, PlayerProjection
from ninecat.warehouse.projections import import_projections_csv

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "projections" / "sample_projections.csv"

JOKIC_PERSON_ID = 1
EDWARDS_PERSON_ID = 2
SABONIS_PERSON_ID = 3

SEASON = "2025-26"
SOURCE = "test-source"


def _seed_players(db_session):
    db_session.add_all(
        [
            NbaPlayer(nba_person_id=JOKIC_PERSON_ID, full_name="Nikola Jokic"),
            NbaPlayer(nba_person_id=EDWARDS_PERSON_ID, full_name="Anthony Edwards"),
            NbaPlayer(nba_person_id=SABONIS_PERSON_ID, full_name="Domantas Sabonis"),
        ]
    )
    db_session.flush()


def test_import_projections_csv_creates_rows_spot_checks_and_reports_unmatched(db_session):
    _seed_players(db_session)

    result = import_projections_csv(db_session, FIXTURE_PATH, source_name=SOURCE, season=SEASON)
    db_session.flush()

    # 3 real players matched, the deliberately misspelled "Nikola Jokicc" row unmatched
    assert result.imported == 3
    assert result.unmatched == ["Nikola Jokicc"]

    rows = db_session.execute(select(PlayerProjection)).scalars().all()
    assert len(rows) == 3

    edwards = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == EDWARDS_PERSON_ID)
    ).scalar_one()
    projection = db_session.execute(
        select(PlayerProjection).where(PlayerProjection.nba_player_id == edwards.id)
    ).scalar_one()
    assert projection.tpm == 3.1
    assert projection.projected_games == 75
    assert projection.season == SEASON
    assert projection.source == SOURCE


def test_import_projections_csv_rerun_with_changed_value_updates_in_place(db_session):
    _seed_players(db_session)
    import_projections_csv(db_session, FIXTURE_PATH, source_name=SOURCE, season=SEASON)
    db_session.flush()

    # write a mutated copy of the fixture (Jokic's pts bumped) to prove the
    # second import hits the DO UPDATE branch, not just re-inserts equal rows
    mutated_path = FIXTURE_PATH.parent / "_mutated_for_test.csv"
    with FIXTURE_PATH.open(newline="") as src:
        rows = list(csv.DictReader(src))
    for row in rows:
        if row["player"] == "Nikola Jokic":
            row["pts"] = "35.0"
    with mutated_path.open("w", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    try:
        result = import_projections_csv(
            db_session, mutated_path, source_name=SOURCE, season=SEASON
        )
        db_session.flush()
        # expire_all forces the next reads through postgres rather than the
        # session's identity map, so this actually proves the row was updated
        db_session.expire_all()
    finally:
        mutated_path.unlink(missing_ok=True)

    assert result.imported == 3
    rows_after = db_session.execute(select(PlayerProjection)).scalars().all()
    assert len(rows_after) == 3

    jokic = db_session.execute(
        select(NbaPlayer).where(NbaPlayer.nba_person_id == JOKIC_PERSON_ID)
    ).scalar_one()
    projection = db_session.execute(
        select(PlayerProjection).where(PlayerProjection.nba_player_id == jokic.id)
    ).scalar_one()
    assert projection.pts == 35.0


def test_import_projections_csv_missing_column_raises_value_error(db_session, tmp_path):
    bad_csv = tmp_path / "missing_columns.csv"
    # missing "tpm" and "tov"
    bad_csv.write_text(
        "player,team,games,fgm,fga,ftm,fta,pts,reb,ast,stl,blk\n"
        "Nikola Jokic,DEN,70,10.5,18.2,6.1,7.0,29.6,11.8,9.8,1.2,0.7\n"
    )

    with pytest.raises(ValueError) as exc_info:
        import_projections_csv(db_session, bad_csv, source_name=SOURCE, season=SEASON)

    message = str(exc_info.value)
    assert "tpm" in message
    assert "tov" in message


def test_import_projections_csv_duplicate_player_raises_value_error(db_session, tmp_path):
    _seed_players(db_session)
    dup_csv = tmp_path / "duplicate_player.csv"
    # same player ("Nikola Jokic") listed twice -- must fail loudly rather
    # than hit Postgres' multi-row ON CONFLICT error deep in the upsert
    dup_csv.write_text(
        "player,team,games,fgm,fga,ftm,fta,tpm,pts,reb,ast,stl,blk,tov\n"
        "Nikola Jokic,DEN,70,10.5,18.2,6.1,7.0,1.2,29.6,11.8,9.8,1.2,0.7,3.0\n"
        "Nikola Jokic,DEN,70,10.5,18.2,6.1,7.0,1.2,29.6,11.8,9.8,1.2,0.7,3.0\n"
    )

    with pytest.raises(ValueError) as exc_info:
        import_projections_csv(db_session, dup_csv, source_name=SOURCE, season=SEASON)
    db_session.flush()

    assert "Nikola Jokic" in str(exc_info.value)
    # nothing was written -- the duplicate check runs entirely before any insert
    rows = db_session.execute(select(PlayerProjection)).scalars().all()
    assert len(rows) == 0


def test_import_projections_csv_ambiguous_normalized_name_is_unmatched(db_session):
    # two real NbaPlayer rows with different exact full_name strings that
    # both normalize to "michael porter" (suffix-stripped) -- the CSV's
    # unsuffixed "Michael Porter" can't be resolved between them
    db_session.add_all(
        [
            NbaPlayer(nba_person_id=10, full_name="Michael Porter Jr"),
            NbaPlayer(nba_person_id=11, full_name="Michael Porter Jr."),
        ]
    )
    db_session.flush()

    ambiguous_csv = FIXTURE_PATH.parent / "_ambiguous_for_test.csv"
    ambiguous_csv.write_text(
        "player,team,games,fgm,fga,ftm,fta,tpm,pts,reb,ast,stl,blk,tov\n"
        "Michael Porter,DEN,70,6.0,12.0,2.0,2.5,2.0,16.0,6.5,2.0,0.8,0.5,1.5\n"
    )

    try:
        result = import_projections_csv(
            db_session, ambiguous_csv, source_name=SOURCE, season=SEASON
        )
        db_session.flush()
    finally:
        ambiguous_csv.unlink(missing_ok=True)

    assert result.imported == 0
    assert result.unmatched == ["Michael Porter"]
    rows = db_session.execute(select(PlayerProjection)).scalars().all()
    assert len(rows) == 0


# --- migration ---

BACKEND_DIR = Path(__file__).resolve().parents[1]
PRIOR_HEAD = "38e1e360f829"


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

    # leaves the db back at head so it doesn't strand the rest of the suite
    assert ScriptDirectory.from_config(cfg).get_current_head() is not None
