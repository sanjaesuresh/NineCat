import pytest

from ninecat.engine.matchup import (
    CLOSE_MARGIN_ABS_PCT,
    CLOSE_MARGIN_RATIO,
    CategoryVerdict,
    compare_matchup,
)
from ninecat.engine.weekly import WeeklyProjection
from ninecat.engine.zscores import CATEGORIES

TOL = 1e-9


def _projection(games=0.0, **totals) -> WeeklyProjection:
    # helper: a WeeklyProjection with all 9 categories defaulting to 0.0,
    # overridden per test -- components/player_games are irrelevant to
    # matchup.py (it only reads .totals and .games), so they're filled with
    # placeholders; games defaults to 0.0 (irrelevant to most tests) but is
    # overridable for the tests that assert on mine_games/their_games
    base = {cat: 0.0 for cat in CATEGORIES}
    base.update(totals)
    return WeeklyProjection(
        totals=base,
        components={"fgm": 0.0, "fga": 0.0, "ftm": 0.0, "fta": 0.0},
        games=games,
        player_games={},
    )


def test_clear_win_and_clear_loss():
    # pts: mine 120 vs theirs 80, margin 40, combined 200 -> ratio 40/200=0.20
    # far past CLOSE_MARGIN_RATIO (0.05) -> winning
    # reb: mine 30 vs theirs 60, margin -30, combined 90 -> ratio 0.333 -> losing
    mine = _projection(pts=120.0, reb=30.0)
    theirs = _projection(pts=80.0, reb=60.0)

    result = compare_matchup(mine, theirs)
    by_cat = {cv.category: cv for cv in result.categories}

    assert by_cat["pts"].margin == pytest.approx(40.0, abs=TOL)
    assert by_cat["pts"].verdict == "winning"
    assert by_cat["reb"].margin == pytest.approx(-30.0, abs=TOL)
    assert by_cat["reb"].verdict == "losing"


def test_counting_category_small_relative_margin_close_larger_margin_not_close():
    # NOT a boundary pin (margins here are nowhere near CLOSE_MARGIN_RATIO *
    # combined) -- this just confirms a comfortably-small relative margin
    # reads close and a comfortably-larger one doesn't. See
    # test_close_call_boundary_at_exact_threshold_is_close for the actual
    # boundary pin.
    # ast: mine 105, theirs 100 -> combined 205, margin 5
    #   threshold = CLOSE_MARGIN_RATIO * 205 = 10.25 -> abs(5) <= 10.25 -> close
    # stl: mine 111, theirs 100 -> combined 211, margin 11
    #   threshold = CLOSE_MARGIN_RATIO * 211 = 10.55 -> abs(11) > 10.55 -> winning (not close)
    mine = _projection(ast=105.0, stl=111.0)
    theirs = _projection(ast=100.0, stl=100.0)

    result = compare_matchup(mine, theirs)
    by_cat = {cv.category: cv for cv in result.categories}

    assert by_cat["ast"].verdict == "close"
    assert by_cat["stl"].verdict == "winning"


def test_close_call_boundary_at_exact_threshold_is_close():
    # tpm: mine 21, theirs 20 -> combined 41, margin 1
    #   threshold = CLOSE_MARGIN_RATIO * 41 = 2.05 -> abs(1) <= 2.05 -> close
    # blk: choose margin exactly equal to the threshold so the "<=" boundary
    #   itself is pinned: mine 10.5, theirs 9.5 -> combined 20, margin 1,
    #   threshold = 0.05*20 = 1.0 exactly -> abs(1.0) <= 1.0 -> close (inclusive)
    mine = _projection(tpm=21.0, blk=10.5)
    theirs = _projection(tpm=20.0, blk=9.5)

    result = compare_matchup(mine, theirs)
    by_cat = {cv.category: cv for cv in result.categories}

    assert by_cat["tpm"].verdict == "close"
    assert by_cat["blk"].verdict == "close"


def test_percentage_category_boundary_at_close_margin_abs_pct_is_close():
    # fg_pct/ft_pct use the ABSOLUTE threshold CLOSE_MARGIN_ABS_PCT, not
    # CLOSE_MARGIN_RATIO * combined -- derive mine from theirs + the actual
    # constant so the boundary is pinned against the real value, not a
    # hand-typed float that could drift if the constant is retuned. (The
    # float subtraction lands a few ULPs below the constant, same rounding
    # behavior as any float boundary -- still satisfies the "<=" inclusive
    # comparison the implementation uses.)
    theirs_pct = 0.60
    mine_pct = theirs_pct + CLOSE_MARGIN_ABS_PCT
    mine = _projection(fg_pct=mine_pct)
    theirs = _projection(fg_pct=theirs_pct)

    result = compare_matchup(mine, theirs)
    fg_verdict = next(cv for cv in result.categories if cv.category == "fg_pct")

    assert fg_verdict.verdict == "close"


def test_percentage_category_just_beyond_close_margin_abs_pct_is_not_close():
    # same construction as the inclusive-boundary test, but pushed 0.1
    # percentage points past CLOSE_MARGIN_ABS_PCT -- must read as a real
    # (winning) gap, not close.
    theirs_pct = 0.60
    mine_pct = theirs_pct + CLOSE_MARGIN_ABS_PCT + 0.001
    mine = _projection(ft_pct=mine_pct)
    theirs = _projection(ft_pct=theirs_pct)

    result = compare_matchup(mine, theirs)
    ft_verdict = next(cv for cv in result.categories if cv.category == "ft_pct")

    assert ft_verdict.verdict == "winning"


def test_percentage_category_four_point_gap_is_a_blowout_not_close():
    # regression pin for I1: the proportional rule (CLOSE_MARGIN_RATIO *
    # combined ~1.0) used to classify BOTH of these real reviewer-reported
    # cases as "close" -- a 4-point weekly FG% gap that no single streamed
    # add closes. With CLOSE_MARGIN_ABS_PCT (0.0075) both must now read as
    # decisive results.
    mine_a = _projection(fg_pct=0.500)
    theirs_a = _projection(fg_pct=0.460)
    result_a = compare_matchup(mine_a, theirs_a)
    assert next(cv for cv in result_a.categories if cv.category == "fg_pct").verdict == "winning"

    mine_b = _projection(fg_pct=0.480)
    theirs_b = _projection(fg_pct=0.440)
    result_b = compare_matchup(mine_b, theirs_b)
    assert next(cv for cv in result_b.categories if cv.category == "fg_pct").verdict == "winning"


def test_close_margin_abs_pct_is_exported_constant():
    assert CLOSE_MARGIN_ABS_PCT == 0.0075


def test_turnover_orientation_fewer_turnovers_reads_as_winning():
    # mine has FEWER turnovers (10) than theirs (20) -- a knowledgeable fan
    # expects this to read "winning" in tov, and contribute to my score, even
    # though 10 < 20 would look like a "loss" under a naive mine-minus-theirs
    # comparison that forgot turnovers invert.
    mine = _projection(tov=10.0)
    theirs = _projection(tov=20.0)

    result = compare_matchup(mine, theirs)
    tov_verdict = next(cv for cv in result.categories if cv.category == "tov")

    # raw totals are reported unoriented (real numbers), margin is oriented
    assert tov_verdict.mine == 10.0
    assert tov_verdict.theirs == 20.0
    assert tov_verdict.margin == pytest.approx(10.0, abs=TOL)  # theirs - mine
    assert tov_verdict.verdict == "winning"


def test_turnover_orientation_more_turnovers_reads_as_losing():
    mine = _projection(tov=25.0)
    theirs = _projection(tov=15.0)

    result = compare_matchup(mine, theirs)
    tov_verdict = next(cv for cv in result.categories if cv.category == "tov")

    assert tov_verdict.margin == pytest.approx(-10.0, abs=TOL)  # theirs - mine
    assert tov_verdict.verdict == "losing"


def test_zero_zero_category_reads_tie_but_is_excluded_from_close_categories():
    # neither side projects any blocks this week (e.g. bye week / no bigs
    # rostered, or -- the realistic case -- no NBA schedule rows at all, the
    # dev seed's current state): combined is 0, so the ratio formula must not
    # blow up. This reads "tie" (margin == 0, exact equality), but a 0-0
    # reading is almost always MISSING DATA rather than a genuinely level
    # contest, so it must stay out of close_categories/focus -- offering it
    # as the #1 flip target would send the streaming optimizer chasing a
    # phantom category with nothing behind it.
    mine = _projection(blk=0.0)
    theirs = _projection(blk=0.0)

    result = compare_matchup(mine, theirs)
    blk_verdict = next(cv for cv in result.categories if cv.category == "blk")

    assert blk_verdict.margin == 0.0
    assert blk_verdict.verdict == "tie"
    assert "blk" not in result.close_categories
    assert "blk" not in result.focus
    # the tie contributes to neither side's projected_score
    assert result.projected_score == (0, 0)


def test_nonzero_exact_tie_reads_tie_and_is_an_actionable_close_target():
    # a genuinely dead-level category with real production behind it (45-45
    # points): margin is exactly 0, same as the 0-0 case, but here there IS
    # real volume, so unlike 0-0 this is exactly what the streaming optimizer
    # should be chasing -- it must appear in close_categories/focus.
    mine = _projection(pts=45.0)
    theirs = _projection(pts=45.0)

    result = compare_matchup(mine, theirs)
    pts_verdict = next(cv for cv in result.categories if cv.category == "pts")

    assert pts_verdict.margin == 0.0
    assert pts_verdict.verdict == "tie"
    assert "pts" in result.close_categories
    assert "pts" in result.focus
    # still contributes to neither side's projected_score, same as 0-0
    assert result.projected_score == (0, 0)


def test_projected_score_sums_across_mixed_nine_category_matchup():
    # hand-counted: I win fg_pct, tpm, pts, reb (4). They win ft_pct, ast,
    # stl, blk (4). tov is an exact tie (both 15) and counts to neither.
    # projected_score must be (4, 4).
    mine = _projection(
        fg_pct=0.50, ft_pct=0.70, tpm=15.0, pts=110.0, reb=50.0,
        ast=20.0, stl=8.0, blk=5.0, tov=15.0,
    )
    theirs = _projection(
        fg_pct=0.45, ft_pct=0.80, tpm=10.0, pts=100.0, reb=40.0,
        ast=25.0, stl=10.0, blk=8.0, tov=15.0,
    )

    result = compare_matchup(mine, theirs)

    assert result.projected_score == (4, 4)
    tov_verdict = next(cv for cv in result.categories if cv.category == "tov")
    assert tov_verdict.verdict == "tie"
    # a real, nonzero exact tie is still an actionable streaming target
    assert "tov" in result.close_categories


def test_focus_orders_most_flippable_close_category_first():
    # two close categories with different relative margins:
    #   ast: mine 102, theirs 100 -> combined 202, ratio 2/202 = 0.0099
    #   stl: mine 105, theirs 100 -> combined 205, ratio 5/205 = 0.0244
    # both within CLOSE_MARGIN_RATIO (0.05), so both are close, but ast has
    # the smaller relative margin -> more flippable -> must come first.
    mine = _projection(ast=102.0, stl=105.0)
    theirs = _projection(ast=100.0, stl=100.0)

    result = compare_matchup(mine, theirs)

    assert set(result.close_categories) == {"ast", "stl"}
    assert result.focus == ("ast", "stl")


def test_fan_plausibility_bigs_win_blocks_rebounds_guards_win_assists_threes():
    # a realistic "bigs" roster projects big rebounds/blocks and few assists
    # or threes; a "guards" roster projects the mirror image. A knowledgeable
    # fan reading this matchup expects bigs to read winning in blk/reb and
    # losing in ast/tpm, and the reverse for guards -- this pins the whole
    # comparison pipeline against a plausible real-world shape, not just
    # arithmetic in isolation.
    #
    # unlike weekly.py, compare_matchup does not compute a weighted aggregate
    # from multiple inputs -- it only compares two already-computed totals --
    # so the direction assertions below are not vulnerable to weekly's
    # element-wise-dominance blind spot. But the verdict strings alone don't
    # pin the ORIENTATION rule (tov) or the SCORE-TALLY rule (projected_score)
    # exactly, both of which are this module's own domain logic (see module
    # docstring) and both fragile to a one-line mutation that a "winning"/
    # "losing" string would not always distinguish from a swapped tally.
    # Exact margins, and the exact projected_score, close that gap.
    bigs = _projection(
        fg_pct=0.55, ft_pct=0.65, tpm=4.0, pts=140.0,
        reb=90.0, ast=25.0, stl=10.0, blk=20.0, tov=18.0,
    )
    guards = _projection(
        fg_pct=0.44, ft_pct=0.85, tpm=35.0, pts=150.0,
        reb=35.0, ast=70.0, stl=15.0, blk=3.0, tov=20.0,
    )

    result = compare_matchup(bigs, guards)
    by_cat = {cv.category: cv for cv in result.categories}

    assert by_cat["reb"].verdict == "winning"
    assert by_cat["blk"].verdict == "winning"
    assert by_cat["ast"].verdict == "losing"
    assert by_cat["tpm"].verdict == "losing"
    # bigs also have fewer turnovers here -> winning tov despite the raw
    # 18 < 20 looking like a marginal number, confirming orientation holds
    # end-to-end in a realistic matchup, not just an isolated unit test
    assert by_cat["tov"].verdict == "winning"

    # exact hand-computed margins (mine=bigs, theirs=guards; margin = mine -
    # theirs except tov, which is theirs - mine per _oriented_margin):
    #   reb: 90 - 35 = 55
    #   blk: 20 - 3  = 17
    #   ast: 25 - 70 = -45
    #   tpm: 4  - 35 = -31
    #   tov: 20 - 18 = 2   (theirs - mine: bigs commit FEWER turnovers, 18 <
    #        20, so bigs' oriented advantage is positive)
    assert by_cat["reb"].margin == pytest.approx(55.0, abs=TOL)
    assert by_cat["blk"].margin == pytest.approx(17.0, abs=TOL)
    assert by_cat["ast"].margin == pytest.approx(-45.0, abs=TOL)
    assert by_cat["tpm"].margin == pytest.approx(-31.0, abs=TOL)
    assert by_cat["tov"].margin == pytest.approx(2.0, abs=TOL)

    # projected_score: whoever's margin is positive wins the category.
    # mine (bigs) is ahead in fg_pct (0.11), reb (55), blk (17), tov (2) = 4.
    # theirs (guards) is ahead in ft_pct (-0.20), tpm (-31), pts (-10,
    # combined 290 -> threshold 14.5, still "close" not "winning" but STILL
    # counts to theirs since projected_score only cares about margin sign),
    # ast (-45), stl (-5) = 5. This is sensitive to BOTH the tov sign (losing
    # the flip moves tov from mine's column to theirs', changing the score to
    # (3, 6)) and to which counter counts which side (swapping the two sums
    # would read (5, 4)).
    assert result.projected_score == (4, 5)


def test_categories_are_in_canonical_order():
    mine = _projection()
    theirs = _projection()

    result = compare_matchup(mine, theirs)

    assert tuple(cv.category for cv in result.categories) == CATEGORIES


def test_comparison_is_deterministic_across_repeated_calls():
    mine = _projection(
        fg_pct=0.50, ft_pct=0.70, tpm=15.0, pts=110.0, reb=50.0,
        ast=20.0, stl=8.0, blk=5.0, tov=15.0,
    )
    theirs = _projection(
        fg_pct=0.45, ft_pct=0.80, tpm=10.0, pts=100.0, reb=40.0,
        ast=25.0, stl=10.0, blk=8.0, tov=15.0,
    )

    first = compare_matchup(mine, theirs)
    second = compare_matchup(mine, theirs)

    assert first == second


def test_category_verdict_is_a_frozen_dataclass_instance():
    mine = _projection(pts=100.0)
    theirs = _projection(pts=90.0)

    result = compare_matchup(mine, theirs)

    assert all(isinstance(cv, CategoryVerdict) for cv in result.categories)
    with pytest.raises(AttributeError):
        result.categories[0].margin = 999.0  # frozen -> mutation raises


def test_close_margin_ratio_is_exported_constant():
    assert CLOSE_MARGIN_RATIO == 0.05


def test_zero_games_side_is_visible_in_result():
    # I2: compare_matchup used to discard WeeklyProjection.games entirely,
    # so a side with no schedule rows (unsynced/stale schedule, or a real
    # league before its first week's games land) produced a comparison
    # indistinguishable from one built on real data. mine_games/their_games
    # carry that data-quality signal through so a caller can guard on it
    # without re-deriving it from the raw projections itself.
    mine = _projection(games=0.0, pts=0.0)
    theirs = _projection(games=12.0, pts=80.0)

    result = compare_matchup(mine, theirs)

    assert result.mine_games == 0.0
    assert result.their_games == 12.0


def test_both_sides_games_carried_through_when_data_present():
    mine = _projection(games=10.0)
    theirs = _projection(games=14.0)

    result = compare_matchup(mine, theirs)

    assert result.mine_games == 10.0
    assert result.their_games == 14.0
