from sqlalchemy import select

from ninecat.models import NbaPlayer, PlayerIdMap
from ninecat.warehouse.id_mapping import map_yahoo_players, normalize_name
from ninecat.yahoo.parsers import RosterEntry


def _roster_entry(key: str, name: str) -> RosterEntry:
    return RosterEntry(
        player_key=key,
        name=name,
        eligible_positions=["PG"],
        selected_position="PG",
        injury_status=None,
        nba_team_abbr="BOS",
    )


def test_normalize_name_strips_diacritics_punctuation_and_suffix():
    assert normalize_name("Luka Dončić") == "luka doncic"
    assert normalize_name("Jaren Jackson Jr.") == "jaren jackson"
    assert normalize_name("Jaren Jackson Jr") == "jaren jackson"


def test_normalize_name_deletes_periods_and_apostrophes_without_spacing():
    # periods/apostrophes must fuse their neighbors (not split into new
    # tokens), unlike a hyphen which stays a real word boundary
    assert normalize_name("P.J. Washington") == normalize_name("PJ Washington") == "pj washington"
    assert normalize_name("De'Aaron Fox") == normalize_name("DeAaron Fox") == "deaaron fox"


def test_map_yahoo_players_matches_via_normalization(db_session):
    db_session.add(NbaPlayer(nba_person_id=1, full_name="Luka Doncic"))
    db_session.flush()

    result = map_yahoo_players(db_session, [_roster_entry("nba.p.1", "Luka Dončić")])
    db_session.flush()

    assert result.normalized_matches == 1
    assert result.exact_matches == 0
    assert result.unmatched == []
    row = db_session.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "nba.p.1")
    ).scalar_one()
    assert row.match_method == "normalized"
    assert row.nba_player_id is not None


def test_map_yahoo_players_matches_suffix_and_punctuation_variant(db_session):
    db_session.add(NbaPlayer(nba_person_id=2, full_name="Jaren Jackson Jr"))
    db_session.flush()

    result = map_yahoo_players(db_session, [_roster_entry("nba.p.2", "Jaren Jackson Jr.")])
    db_session.flush()

    assert result.normalized_matches == 1
    row = db_session.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "nba.p.2")
    ).scalar_one()
    assert row.match_method == "normalized"


def test_map_yahoo_players_exact_match_beats_normalized(db_session):
    # "Jaren Jackson Jr" and "Jaren Jackson" share the same normalized form
    # ("jaren jackson", since the suffix strips off the first one) -- if exact
    # match didn't run before/instead of normalized, this pair would look
    # ambiguous at the normalized stage and land as unmatched instead
    exact_player = NbaPlayer(nba_person_id=3, full_name="Jaren Jackson Jr")
    other_player = NbaPlayer(nba_person_id=30, full_name="Jaren Jackson")
    db_session.add_all([exact_player, other_player])
    db_session.flush()

    result = map_yahoo_players(db_session, [_roster_entry("nba.p.3", "Jaren Jackson Jr")])
    db_session.flush()

    assert result.exact_matches == 1
    assert result.normalized_matches == 0
    assert result.unmatched == []
    row = db_session.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "nba.p.3")
    ).scalar_one()
    assert row.match_method == "exact"
    assert row.nba_player_id == exact_player.id


def test_map_yahoo_players_ambiguous_duplicate_name_is_unmatched(db_session):
    db_session.add_all(
        [
            NbaPlayer(nba_person_id=4, full_name="Jalen Williams"),
            NbaPlayer(nba_person_id=5, full_name="Jalen Williams"),
        ]
    )
    db_session.flush()

    result = map_yahoo_players(db_session, [_roster_entry("nba.p.4", "Jalen Williams")])
    db_session.flush()

    assert result.exact_matches == 0
    assert result.normalized_matches == 0
    assert result.unmatched == ["Jalen Williams"]
    row = db_session.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "nba.p.4")
    ).scalar_one()
    assert row.match_method == "unmatched"
    assert row.nba_player_id is None


def test_map_yahoo_players_unmatched_name_creates_null_row_and_appears_in_result(db_session):
    result = map_yahoo_players(db_session, [_roster_entry("nba.p.6", "Nonexistent Guy")])
    db_session.flush()

    assert result.unmatched == ["Nonexistent Guy"]
    row = db_session.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "nba.p.6")
    ).scalar_one()
    assert row.nba_player_id is None
    assert row.match_method == "unmatched"


def test_map_yahoo_players_never_overwrites_existing_manual_row(db_session):
    manual_player = NbaPlayer(nba_person_id=7, full_name="Manual Match Guy")
    db_session.add(manual_player)
    db_session.flush()
    db_session.add(
        PlayerIdMap(
            nba_player_id=manual_player.id,
            yahoo_player_key="nba.p.7",
            yahoo_name="Manually Fixed Name",
            match_method="manual",
        )
    )
    db_session.flush()

    result = map_yahoo_players(
        db_session, [_roster_entry("nba.p.7", "Some Totally Different Yahoo Name")]
    )
    db_session.flush()

    assert result.already_mapped == 1
    assert result.unmatched == []
    assert result.exact_matches == 0
    assert result.normalized_matches == 0
    row = db_session.execute(
        select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "nba.p.7")
    ).scalar_one()
    assert row.match_method == "manual"
    assert row.yahoo_name == "Manually Fixed Name"


def test_map_yahoo_players_is_idempotent_on_rerun(db_session):
    db_session.add(NbaPlayer(nba_person_id=8, full_name="Luka Doncic"))
    db_session.flush()

    map_yahoo_players(db_session, [_roster_entry("nba.p.8", "Luka Dončić")])
    db_session.flush()
    result = map_yahoo_players(db_session, [_roster_entry("nba.p.8", "Luka Dončić")])
    db_session.flush()

    assert result.already_mapped == 1
    assert result.normalized_matches == 0
    rows = (
        db_session.execute(
            select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "nba.p.8")
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


def test_map_yahoo_players_dedupes_duplicate_player_key_in_single_call(db_session):
    # a caller could hand the same roster entry to map_yahoo_players twice in
    # one batch; without dedupe, a single multi-row insert targeting the same
    # yahoo_player_key twice would be rejected by postgres outright
    db_session.add(NbaPlayer(nba_person_id=9, full_name="Dup Test Guy"))
    db_session.flush()

    entry = _roster_entry("nba.p.9", "Dup Test Guy")
    result = map_yahoo_players(db_session, [entry, entry])
    db_session.flush()

    assert result.exact_matches == 1
    rows = (
        db_session.execute(
            select(PlayerIdMap).where(PlayerIdMap.yahoo_player_key == "nba.p.9")
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
