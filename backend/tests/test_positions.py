from ninecat.engine.positions import SLOT_CLASSES, slot_classes


def test_slot_classes_constant_is_the_canonical_eight_in_order():
    assert SLOT_CLASSES == ("PG", "SG", "G", "SF", "PF", "F", "C", "UTIL")


def test_none_position_is_util_only():
    assert slot_classes(None) == frozenset({"UTIL"})


def test_blank_position_is_util_only():
    assert slot_classes("") == frozenset({"UTIL"})
    assert slot_classes("   ") == frozenset({"UTIL"})


def test_unrecognizable_position_is_util_only():
    assert slot_classes("Mascot") == frozenset({"UTIL"})


# --- long forms ---------------------------------------------------------
def test_long_guard_covers_both_guard_slots_generic_g_and_util():
    assert slot_classes("Guard") == frozenset({"PG", "SG", "G", "UTIL"})


def test_long_forward_covers_both_forward_slots_generic_f_and_util():
    assert slot_classes("Forward") == frozenset({"SF", "PF", "F", "UTIL"})


def test_long_center_covers_center_and_util_only():
    assert slot_classes("Center") == frozenset({"C", "UTIL"})


def test_long_hyphenated_guard_forward_unions_both_sides():
    assert slot_classes("Guard-Forward") == frozenset(
        {"PG", "SG", "G", "SF", "PF", "F", "UTIL"}
    )


# --- short forms ---------------------------------------------------------
def test_short_pg_is_more_specific_than_generic_guard():
    # a player explicitly labeled PG is not automatically SG-eligible
    assert slot_classes("PG") == frozenset({"PG", "G", "UTIL"})


def test_short_sg():
    assert slot_classes("SG") == frozenset({"SG", "G", "UTIL"})


def test_short_sf():
    assert slot_classes("SF") == frozenset({"SF", "F", "UTIL"})


def test_short_pf():
    assert slot_classes("PF") == frozenset({"PF", "F", "UTIL"})


def test_short_c_same_as_long_center():
    assert slot_classes("C") == frozenset({"C", "UTIL"})


def test_short_generic_g_same_as_long_guard():
    assert slot_classes("G") == frozenset({"PG", "SG", "G", "UTIL"})


def test_short_generic_f_same_as_long_forward():
    assert slot_classes("F") == frozenset({"SF", "PF", "F", "UTIL"})


def test_short_hyphenated_f_c_unions_forward_and_center():
    assert slot_classes("F-C") == frozenset({"SF", "PF", "F", "C", "UTIL"})


# --- parsing tolerance -----------------------------------------------------
def test_slash_separated_multi_position_is_also_parsed():
    assert slot_classes("PG/SG") == frozenset({"PG", "SG", "G", "UTIL"})


def test_case_insensitive_and_whitespace_tolerant():
    assert slot_classes("  guard - forward  ") == slot_classes("Guard-Forward")
    assert slot_classes("pg") == slot_classes("PG")


def test_comma_separated_position_is_also_parsed():
    # Yahoo's display_position field is comma-delimited ("PG,SG"), unlike
    # nba_api's hyphen/slash forms
    assert slot_classes("PG,SG") == frozenset({"PG", "SG", "G", "UTIL"})


def test_partially_unrecognizable_token_still_returns_recognized_side():
    # one bad token alongside a good one: the good token's classes still apply
    assert slot_classes("PG-Mascot") == frozenset({"PG", "G", "UTIL"})


def test_every_non_none_recognized_result_includes_util():
    for position in ("PG", "SG", "SF", "PF", "C", "G", "F", "Guard", "Forward", "Center"):
        assert "UTIL" in slot_classes(position)
