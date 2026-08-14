import pytest

from ninecat.engine.build_profile import compute_team_profile
from ninecat.engine.roster_compare import (
    FRAGILE_SHARE,
    MEANINGFUL_Z,
    RosterPlayer,
    compare_rosters,
)
from ninecat.engine.zscores import CATEGORIES

TOL = 1e-6


def _zero_cats(**overrides):
    # helper: a full 9-cat z dict defaulting every category to 0.0, with only
    # the categories under test overridden — mirrors test_build_profile.py
    base = {cat: 0.0 for cat in CATEGORIES}
    base.update(overrides)
    return base


def _player(key, **overrides):
    return RosterPlayer(player_key=key, zscores=_zero_cats(**overrides))


# --- THE HEADLINE TEST -------------------------------------------------------


def test_one_man_category_is_strong_but_fragile_and_excluded_from_surplus():
    # "mine" is strong in blk (mean 0.366667 >= 0.35) solely because of one
    # elite center; the other two players are actively bad shot-blockers.
    #   total = 1.5 - 0.2 - 0.2 = 1.1, mean = 1.1/3 = 0.366667 -> strong
    #   depth: only the center clears MEANINGFUL_Z (0.5) -> depth = 1
    #   positive sum = 1.5 (only the center); top_share = 1.5/1.5 = 1.0
    #   fragile: strong AND (depth<=1 OR top_share>=0.5) -> True (both trip)
    mine = [
        _player("elite_center", blk=1.5),
        _player("bad_blocker_1", blk=-0.2),
        _player("bad_blocker_2", blk=-0.2),
    ]
    # "theirs" is an EQUALLY-strong blk category (also clears STRONG_MEAN_Z)
    # spread across three genuine contributors instead of one.
    #   total = 1.5, mean = 1.5/3 = 0.5 -> strong
    #   depth: all three clear MEANINGFUL_Z (0.5) -> depth = 3
    #   positive sum = 1.5; top_share = 0.5/1.5 = 0.333333 (< 0.5)
    #   fragile: strong AND (depth<=1 OR top_share>=0.5) -> False (neither trips)
    theirs = [
        _player("spread_a", blk=0.5),
        _player("spread_b", blk=0.5),
        _player("spread_c", blk=0.5),
    ]

    result = compare_rosters(mine, theirs)

    mine_blk = result.mine["blk"]
    assert mine_blk.label == "strong"
    assert mine_blk.total == pytest.approx(1.1, abs=TOL)
    assert mine_blk.mean == pytest.approx(0.366667, abs=TOL)
    assert mine_blk.depth == 1
    assert mine_blk.top_contributor == "elite_center"
    assert mine_blk.top_share == pytest.approx(1.0, abs=TOL)
    assert mine_blk.fragile is True
    assert "blk" not in result.my_surplus

    theirs_blk = result.theirs["blk"]
    assert theirs_blk.label == "strong"
    assert theirs_blk.total == pytest.approx(1.5, abs=TOL)
    assert theirs_blk.mean == pytest.approx(0.5, abs=TOL)
    assert theirs_blk.depth == 3
    assert theirs_blk.top_share == pytest.approx(0.333333, abs=TOL)
    assert theirs_blk.fragile is False
    assert "blk" in result.their_surplus


# --- top_share arithmetic -----------------------------------------------------


def test_top_share_excludes_negative_contributors():
    # ast: 1.0, -3.0, 0.5 -- the -3.0 player must NOT enter the denominator,
    # since it doesn't make the positive contribution any less concentrated.
    # positive sum = 1.0 + 0.5 = 1.5; top = 1.0 -> top_share = 1.0/1.5 = 0.666667
    mine = [_player("p1", ast=1.0), _player("p2", ast=-3.0), _player("p3", ast=0.5)]

    result = compare_rosters(mine, [])

    ast = result.mine["ast"]
    assert ast.top_contributor == "p1"
    assert ast.top_share == pytest.approx(0.666667, abs=TOL)


def test_top_share_zero_and_no_contributor_when_every_z_is_negative():
    # tov (already inverted): all three players are negative here -> no
    # positive contributor to the category at all. Must not crash (division
    # guarded) and must report 0.0 share, no top_contributor.
    mine = [_player("p1", tov=-1.0), _player("p2", tov=-0.5), _player("p3", tov=-0.2)]

    result = compare_rosters(mine, [])

    tov = result.mine["tov"]
    assert tov.top_contributor is None
    assert tov.top_share == 0.0
    # total = -1.7, mean = -0.566667 -> punt
    assert tov.label == "punt"
    assert tov.fragile is False


# --- depth boundary -----------------------------------------------------------


def test_depth_counts_at_the_meaningful_z_boundary_both_sides():
    # p1 sits exactly at MEANINGFUL_Z -> counts; p2 sits one part-per-million
    # below it -> does not count; p3 is irrelevant (negative).
    assert MEANINGFUL_Z == 0.5  # pin the constant's value, not just its use
    mine = [
        _player("p1", stl=MEANINGFUL_Z),
        _player("p2", stl=MEANINGFUL_Z - 0.000001),
        _player("p3", stl=-1.0),
    ]

    result = compare_rosters(mine, [])

    assert result.mine["stl"].depth == 1


# --- agreement with build_profile ---------------------------------------------


def test_labels_and_totals_agree_with_compute_team_profile_directly():
    # guards against the two ever drifting: every label/total this module
    # reports must equal what build_profile.compute_team_profile computes on
    # the exact same z dicts.
    roster = [
        _player(
            "p1",
            fg_pct=0.3,
            ft_pct=-0.2,
            tpm=0.1,
            pts=0.5,
            reb=1.2,
            ast=-0.8,
            stl=0.2,
            blk=0.9,
            tov=-0.1,
        ),
        _player(
            "p2",
            fg_pct=-0.1,
            ft_pct=0.4,
            tpm=-0.3,
            pts=0.2,
            reb=0.8,
            ast=-0.5,
            stl=0.4,
            blk=0.6,
            tov=0.2,
        ),
        _player(
            "p3",
            fg_pct=0.2,
            ft_pct=0.1,
            tpm=0.05,
            pts=-0.1,
            reb=1.0,
            ast=-0.6,
            stl=-0.1,
            blk=0.7,
            tov=0.0,
        ),
    ]

    result = compare_rosters(roster, [])
    profile = compute_team_profile([dict(p.zscores) for p in roster])

    for cat in CATEGORIES:
        assert result.mine[cat].label == profile["labels"][cat], cat
        assert result.mine[cat].total == pytest.approx(profile["totals"][cat], abs=TOL), cat


# --- empty / single-player rosters ---------------------------------------------


def test_empty_rosters_never_raise_and_degrade_cleanly():
    result = compare_rosters([], [])

    for side in (result.mine, result.theirs):
        for cat in CATEGORIES:
            strength = side[cat]
            assert strength.label == "average"
            assert strength.depth == 0
            assert strength.fragile is False
            assert strength.top_contributor is None
            assert strength.top_share == 0.0

    assert result.my_surplus == ()
    assert result.my_deficit == ()
    assert result.their_surplus == ()
    assert result.their_deficit == ()


def test_single_player_roster_strength_is_always_fragile():
    # one player IS the whole category: depth can never exceed 1 for a
    # single-player roster, so a "strong" category here is fragile by
    # construction and must never appear in surplus.
    mine = [_player("solo", reb=1.0)]

    result = compare_rosters(mine, [])

    reb = result.mine["reb"]
    assert reb.label == "strong"  # mean = 1.0 >= 0.35
    assert reb.depth == 1
    assert reb.top_contributor == "solo"
    assert reb.top_share == pytest.approx(1.0, abs=TOL)
    assert reb.fragile is True
    assert "reb" not in result.my_surplus


# --- missing category validation -----------------------------------------------


def test_missing_category_key_raises_value_error_naming_player_and_category():
    incomplete = {cat: 0.0 for cat in CATEGORIES if cat != "blk"}
    bad_player = RosterPlayer(player_key="bad_player", zscores=incomplete)

    with pytest.raises(ValueError) as exc_info:
        compare_rosters([bad_player], [])
    message = str(exc_info.value)
    assert "bad_player" in message
    assert "blk" in message

    # the same validation applies to the "theirs" side
    with pytest.raises(ValueError) as exc_info_theirs:
        compare_rosters([], [bad_player])
    assert "bad_player" in str(exc_info_theirs.value)


# --- fan-plausibility (mandatory) ------------------------------------------------


def test_big_heavy_roster_surplus_reb_blk_deficit_ast_tpm_and_reverse_for_guards():
    # three bigs: strong rebound/block, weak assist/three -- a realistic
    # frontcourt-heavy build.
    #
    # membership-only assertions ("reb" in my_surplus) are not sensitive to
    # HOW this module computes mean/depth/top_share -- the bigs-vs-guards gap
    # is so wide (every big's reb/blk z is positive, every guard's is
    # negative) that almost any plausible formula lands on the same "strong"
    # label and the same non-fragile verdict, the same element-wise-dominance
    # blind spot the weekly.py finding describes. Exact total/mean/depth/
    # top_share assertions below pin the actual arithmetic, not just its
    # sign, so a broken mean divisor or a broken concentration formula still
    # fails even though it would not flip any of the membership assertions.
    bigs = [
        _player(
            "big1", reb=1.2, blk=1.0, ast=-0.8, tpm=-1.0, pts=0.2, fg_pct=0.3, ft_pct=-0.2, stl=0.1
        ),
        _player(
            "big2", reb=0.9, blk=0.7, ast=-0.6, tpm=-0.9, pts=0.1, fg_pct=0.2, ft_pct=-0.1, stl=0.0
        ),
        _player(
            "big3", reb=1.0, blk=0.8, ast=-0.7, tpm=-1.1, pts=0.3, fg_pct=0.25, ft_pct=-0.15, stl=0.05
        ),
    ]
    # three guards: the mirror image -- strong assist/three, weak rebound/block.
    guards = [
        _player(
            "guard1", ast=1.0, tpm=0.9, reb=-0.9, blk=-1.0, pts=0.3, fg_pct=-0.1, ft_pct=0.2, stl=0.4
        ),
        _player(
            "guard2", ast=0.8, tpm=1.1, reb=-0.7, blk=-0.8, pts=0.2, fg_pct=-0.05, ft_pct=0.1, stl=0.3
        ),
        _player(
            "guard3", ast=0.9, tpm=1.0, reb=-0.8, blk=-0.9, pts=0.25, fg_pct=-0.15, ft_pct=0.15, stl=0.35
        ),
    ]

    result = compare_rosters(bigs, guards)

    # the big-heavy roster ("mine")
    assert "reb" in result.my_surplus
    assert "blk" in result.my_surplus
    assert "ast" in result.my_deficit
    assert "tpm" in result.my_deficit

    # the guard-heavy roster ("theirs") is the mirror image
    assert "ast" in result.their_surplus
    assert "tpm" in result.their_surplus
    assert "reb" in result.their_deficit
    assert "blk" in result.their_deficit

    # depth is genuine on both sides (three real contributors each), so
    # neither team's surplus categories are fragile
    assert result.mine["reb"].fragile is False
    assert result.mine["blk"].fragile is False
    assert result.theirs["ast"].fragile is False
    assert result.theirs["tpm"].fragile is False

    # exact hand-computed total/mean/depth/top_share (positive-z-only
    # concentration, per _category_strength -- see that function's
    # docstring):
    #   mine reb: 1.2+0.9+1.0=3.1, mean=3.1/3=1.033333; all three clear
    #     MEANINGFUL_Z (0.5) -> depth=3; top=big1's 1.2, positive_sum=3.1
    #     -> top_share=1.2/3.1=0.387097
    #   mine blk: 1.0+0.7+0.8=2.5, mean=0.833333; depth=3; top=big1's 1.0,
    #     positive_sum=2.5 -> top_share=1.0/2.5=0.4
    #   theirs ast: 1.0+0.8+0.9=2.7, mean=0.9; depth=3; top=guard1's 1.0,
    #     positive_sum=2.7 -> top_share=1.0/2.7=0.370370
    #   theirs tpm: 0.9+1.1+1.0=3.0, mean=1.0; depth=3; top=guard2's 1.1,
    #     positive_sum=3.0 -> top_share=1.1/3.0=0.366667
    mine_reb = result.mine["reb"]
    assert mine_reb.total == pytest.approx(3.1, abs=TOL)
    assert mine_reb.mean == pytest.approx(1.033333, abs=TOL)
    assert mine_reb.depth == 3
    assert mine_reb.top_contributor == "big1"
    assert mine_reb.top_share == pytest.approx(0.387097, abs=TOL)

    mine_blk = result.mine["blk"]
    assert mine_blk.total == pytest.approx(2.5, abs=TOL)
    assert mine_blk.mean == pytest.approx(0.833333, abs=TOL)
    assert mine_blk.depth == 3
    assert mine_blk.top_contributor == "big1"
    assert mine_blk.top_share == pytest.approx(0.4, abs=TOL)

    theirs_ast = result.theirs["ast"]
    assert theirs_ast.total == pytest.approx(2.7, abs=TOL)
    assert theirs_ast.mean == pytest.approx(0.9, abs=TOL)
    assert theirs_ast.depth == 3
    assert theirs_ast.top_contributor == "guard1"
    assert theirs_ast.top_share == pytest.approx(0.370370, abs=TOL)

    theirs_tpm = result.theirs["tpm"]
    assert theirs_tpm.total == pytest.approx(3.0, abs=TOL)
    assert theirs_tpm.mean == pytest.approx(1.0, abs=TOL)
    assert theirs_tpm.depth == 3
    assert theirs_tpm.top_contributor == "guard2"
    assert theirs_tpm.top_share == pytest.approx(0.366667, abs=TOL)


# --- determinism ---------------------------------------------------------------


def test_same_inputs_give_identical_results():
    mine = [_player("a", reb=0.8), _player("b", reb=0.6, ast=-0.5)]
    theirs = [_player("c", ast=0.9), _player("d", tpm=1.0)]

    first = compare_rosters(mine, theirs)
    second = compare_rosters(mine, theirs)

    assert first == second


def test_top_contributor_tie_break_is_stable_regardless_of_input_order():
    # both players tie at pts=0.8 -- the winner must be decided by
    # player_key (lexicographically smallest), not by list position.
    forward_order = [_player("z_player", pts=0.8), _player("a_player", pts=0.8)]
    reverse_order = [_player("a_player", pts=0.8), _player("z_player", pts=0.8)]

    forward_result = compare_rosters(forward_order, [])
    reverse_result = compare_rosters(reverse_order, [])

    assert forward_result.mine["pts"].top_contributor == "a_player"
    assert reverse_result.mine["pts"].top_contributor == "a_player"


def test_fragile_share_boundary_is_inclusive():
    # top_share sits exactly at FRAGILE_SHARE -> must still flag fragile
    # (">=", not ">"). p1 supplies exactly half the positive blk z, and a
    # third player clears MEANINGFUL_Z too so depth alone (>1) doesn't save it.
    assert FRAGILE_SHARE == 0.5
    mine = [
        _player("p1", blk=1.0),
        _player("p2", blk=1.0),
        _player("p3", blk=0.0),
    ]
    # total = 2.0, mean = 0.666667 -> strong; depth: both p1,p2 >= 0.5 -> 2
    # positive sum = 2.0; top_share = 1.0/2.0 = 0.5 exactly -> fragile (>=)

    result = compare_rosters(mine, [])

    blk = result.mine["blk"]
    assert blk.depth == 2
    assert blk.top_share == pytest.approx(0.5, abs=TOL)
    assert blk.fragile is True
    assert "blk" not in result.my_surplus
