import pytest

from ninecat.engine.roster_compare import MEANINGFUL_Z, RosterPlayer, compare_rosters
from ninecat.engine.trade_candidates import (
    MATERIAL_MEAN_DELTA,
    CandidateSet,
    generate_trade_candidates,
)
from ninecat.engine.zscores import CATEGORIES

TOL = 1e-6


def _zero_cats(**overrides):
    # helper: a full 9-cat z dict defaulting every category to 0.0, with only
    # the categories under test overridden -- mirrors test_roster_compare.py
    base = {cat: 0.0 for cat in CATEGORIES}
    base.update(overrides)
    return base


def _player(key, **overrides):
    return RosterPlayer(player_key=key, zscores=_zero_cats(**overrides))


# --- THE HEADLINE TEST -------------------------------------------------------


def _headline_rosters():
    # mine: strong+genuine reb surplus (3 real contributors), strong+FRAGILE
    # blk (m1 is the sole positive blk contributor -- same numbers as
    # roster_compare's headline fixture: total 1.1, mean 0.366667, depth 1,
    # top_share 1.0), punt ast deficit (mean -0.4).
    mine = [
        _player("m1", reb=1.0, blk=1.5, ast=-0.4),
        _player("m2", reb=0.9, blk=-0.2, ast=-0.4),
        _player("m3", reb=0.8, blk=-0.2, ast=-0.4),
    ]
    # theirs: strong+genuine ast surplus (3 equal contributors, mean 0.9,
    # top_share 0.370 -- not fragile), punt reb deficit (mean -0.4).
    theirs = [
        _player("t1", ast=1.0, reb=-0.4),
        _player("t2", ast=0.9, reb=-0.4),
        _player("t3", ast=0.8, reb=-0.4),
    ]
    return mine, theirs


def test_trade_that_collapses_a_strong_category_is_rejected():
    # give=m1 is eligible (reb is my surplus and m1's reb=1.0 > 0), but m1 is
    # ALSO the sole positive blk contributor. Post-trade mine = [m2, m3, t1]:
    #   blk: -0.2 -0.2 +0.0(t1 default) = -0.4, mean = -0.1333 -> "average"
    #   (was "strong" at mean 0.366667 pre-trade) -> COLLAPSE -> must be
    #   rejected even though ast (my deficit) genuinely improves:
    #   ast: -0.4 -0.4 +1.0 = 0.2, mean 0.0667 (was punt at -0.4)
    mine, theirs = _headline_rosters()

    result = generate_trade_candidates(mine, theirs, max_package=1)

    rejected = ("m1",), ("t1",)
    assert rejected not in [(c.give, c.get) for c in result.candidates]


def test_similar_trade_that_keeps_both_sides_strong_is_generated():
    # give=m2 (also eligible via reb) is NOT the blk carrier -- trading it
    # away leaves m1 (blk=1.5) on the roster, so blk stays strong.
    # Post-trade mine = [m1, m3, t1]:
    #   blk: 1.5 -0.2 +0.0 = 1.3, mean 0.4333 -> still "strong", no collapse
    #   ast: -0.4 -0.4 +1.0 = 0.2, mean 0.0667 (was punt -0.4) -> improves
    #   reb (unrelated, unaffected by keep-check): 1.0+0.8-0.4=1.4, mean
    #   0.4667 -- still strong, irrelevant since reb isn't a deficit
    # Post-trade theirs = [t2, t3, m2]:
    #   ast: 0.9+0.8-0.4=1.3, mean 0.4333 -> still "strong", no collapse
    #   reb (their deficit): -0.4-0.4+0.9=0.1, mean 0.0333 (was punt -0.4)
    #   -> improves
    mine, theirs = _headline_rosters()

    result = generate_trade_candidates(mine, theirs, max_package=1)

    kept = next(c for c in result.candidates if c.give == ("m2",) and c.get == ("t1",))
    assert "ast" in kept.my_gain
    assert "reb" in kept.their_gain

    # independently confirm via a direct compare_rosters call -- the cheap
    # strong guard that the whole module isn't subtly wrong
    new_mine = [mine[0], mine[2], theirs[0]]  # m1, m3, t1
    new_theirs = [theirs[1], theirs[2], mine[1]]  # t2, t3, m2
    direct = compare_rosters(new_mine, new_theirs)
    assert direct.mine["blk"].label == "strong"
    assert direct.theirs["ast"].label == "strong"


# --- both-sides-improve enforced ----------------------------------------------


def test_trade_that_helps_only_me_is_not_returned():
    # every mine player carries a strongly negative reb (-1.0) -- their
    # deficit category. Swapping any of them in always makes theirs' reb
    # WORSE (removing a -0.4 puller, adding a -1.0 one), so no 1-for-1 candi-
    # date can ever satisfy the both-sides-improve requirement, even though
    # mine's own deficit (ast) genuinely improves on every combination.
    mine = [
        _player("a1", stl=1.0, pts=-0.4, reb=-1.0),
        _player("a2", stl=0.9, pts=-0.4, reb=-1.0),
        _player("a3", stl=0.8, pts=-0.4, reb=-1.0),
    ]
    theirs = [
        _player("b1", tpm=1.0, reb=-0.4),
        _player("b2", tpm=0.9, reb=-0.4),
        _player("b3", tpm=0.8, reb=-0.4),
    ]
    comparison = compare_rosters(mine, theirs)
    assert comparison.my_surplus == ("stl",)
    # reb is punt for mine too (mean -1.0) -- doesn't matter for the
    # assertion below, since pts alone is enough to make "improves_me" true
    # on every combination; the point of this fixture is that theirs never
    # improves
    assert comparison.my_deficit == ("pts", "reb")
    assert comparison.their_surplus == ("tpm",)
    assert comparison.their_deficit == ("reb",)

    result = generate_trade_candidates(mine, theirs, comparison=comparison, max_package=1)

    assert result.candidates == ()
    # confirms combinations were actually examined and rejected, not just
    # never attempted (would also be () if e.g. eligibility were empty)
    assert result.evaluated == 9  # 3 eligible give x 3 eligible get


# --- fragile categories never raided -------------------------------------------


def test_fragile_categorys_sole_carrier_never_appears_as_a_give():
    # elite_blocker is the sole positive blk contributor (strong+fragile,
    # excluded from surplus) but contributes 0 (not positive) to reb, so it
    # is never eligible as a give player at all -- only via a surplus
    # category can a player be sent, and blk isn't one (it's fragile).
    mine = [
        _player("elite_blocker", blk=1.9, reb=0.0, ast=-0.4),
        _player("r1", reb=1.2, blk=-0.1, ast=-0.4),
        _player("r2", reb=1.1, blk=-0.1, ast=-0.4),
        _player("r3", reb=1.0, blk=-0.1, ast=-0.4),
    ]
    theirs = [
        _player("t1", ast=1.0, reb=-0.4),
        _player("t2", ast=0.9, reb=-0.4),
        _player("t3", ast=0.8, reb=-0.4),
    ]
    comparison = compare_rosters(mine, theirs)
    # blk: total 1.9-0.1-0.1-0.1=1.6, mean 0.4 -> strong; depth 1 -> fragile
    assert comparison.mine["blk"].label == "strong"
    assert comparison.mine["blk"].fragile is True
    assert "blk" not in comparison.my_surplus
    # reb: total 1.2+1.1+1.0=3.3, mean 0.825 -> strong; depth 3, top_share
    # 1.2/3.3=0.3636 -> not fragile
    assert "reb" in comparison.my_surplus

    result = generate_trade_candidates(mine, theirs, comparison=comparison, max_package=1)

    assert result.candidates != ()  # the fixture must actually produce trades
    assert all("elite_blocker" not in c.give for c in result.candidates)


def test_positive_but_below_meaningful_z_contributor_is_never_offered():
    # "marginal" is a genuine positive reb contributor (0.3) but below
    # MEANINGFUL_Z (0.5) -- roster_compare doesn't count it toward depth
    # either, and the generator must not treat it as "using the surplus".
    # big1/big2/big3 clear MEANINGFUL_Z and remain eligible.
    assert MEANINGFUL_Z == 0.5  # pin the constant's value, not just its use
    mine = [
        _player("big1", reb=1.2, ast=-0.4),
        _player("big2", reb=0.9, ast=-0.4),
        _player("big3", reb=0.7, ast=-0.4),
        _player("marginal", reb=0.3, ast=-0.4),
    ]
    theirs = [
        _player("t1", ast=1.0, reb=-0.4),
        _player("t2", ast=0.9, reb=-0.4),
        _player("t3", ast=0.8, reb=-0.4),
    ]
    # reb: total 1.2+0.9+0.7+0.3=3.1, mean 0.775 -> strong; depth counts only
    # the three >= MEANINGFUL_Z (marginal's 0.3 doesn't count) -> depth 3;
    # positive sum 3.1, top_share 1.2/3.1=0.387 -> not fragile
    comparison = compare_rosters(mine, theirs)
    assert "reb" in comparison.my_surplus
    assert comparison.mine["reb"].depth == 3

    result = generate_trade_candidates(mine, theirs, comparison=comparison, max_package=1)

    assert result.candidates != ()  # fixture must actually produce trades
    assert all("marginal" not in c.give for c in result.candidates)
    assert any(
        key in c.give for c in result.candidates for key in ("big1", "big2", "big3")
    )


# --- one-for-one and two-for-two -----------------------------------------------


def test_max_package_one_excludes_two_for_two_candidates():
    mine, theirs = _headline_rosters()

    result = generate_trade_candidates(mine, theirs, max_package=1)

    assert result.candidates != ()
    assert all(len(c.give) == 1 and len(c.get) == 1 for c in result.candidates)


def test_max_package_two_includes_both_package_sizes():
    # 4-a-side (rather than the 3-a-side headline fixture) so that removing
    # 2 of 4 depth contributors still leaves each surplus category strong --
    # the headline fixture's 3-a-side rosters collapse on every 2-for-2 swap,
    # which would make this test indistinguishable from the collapse guard.
    mine = [
        _player("m1", reb=1.2, ast=-0.4),
        _player("m2", reb=1.1, ast=-0.4),
        _player("m3", reb=1.0, ast=-0.4),
        _player("m4", reb=0.9, ast=-0.4),
    ]
    theirs = [
        _player("t1", ast=1.2, reb=-0.4),
        _player("t2", ast=1.1, reb=-0.4),
        _player("t3", ast=1.0, reb=-0.4),
        _player("t4", ast=0.9, reb=-0.4),
    ]

    result = generate_trade_candidates(mine, theirs, max_package=2)

    sizes = {len(c.give) for c in result.candidates}
    assert 1 in sizes
    assert 2 in sizes


# --- truncated/evaluated accuracy -----------------------------------------------


def test_truncated_and_evaluated_are_accurate_with_a_tiny_limit():
    # deterministic examination order (give sorted, then get sorted): m1 with
    # any get always collapses blk (rejected) -- 3 combinations examined --
    # then m2+t1 is the 4th combination examined and the first kept one.
    # limit=1 stops right there.
    mine, theirs = _headline_rosters()

    result = generate_trade_candidates(mine, theirs, max_package=1, limit=1)

    assert result.truncated is True
    assert result.evaluated == 4
    assert len(result.candidates) == 1
    assert result.candidates[0].give == ("m2",)
    assert result.candidates[0].get == ("t1",)


def test_not_truncated_when_limit_exceeds_available_candidates():
    mine, theirs = _headline_rosters()

    result = generate_trade_candidates(mine, theirs, max_package=1, limit=25)

    assert result.truncated is False
    assert result.evaluated == 9  # 3 eligible give x 3 eligible get


# --- my_gain/my_loss reflect real post-trade movement ---------------------------


def test_gain_loss_tuples_match_independently_recomputed_compare_rosters():
    mine, theirs = _headline_rosters()

    result = generate_trade_candidates(mine, theirs, max_package=1)
    candidate = next(c for c in result.candidates if c.give == ("m2",) and c.get == ("t1",))

    pre = compare_rosters(mine, theirs)
    new_mine = [mine[0], mine[2], theirs[0]]  # m1, m3, t1
    new_theirs = [theirs[1], theirs[2], mine[1]]  # t2, t3, m2
    post = compare_rosters(new_mine, new_theirs)

    expected_my_gain = tuple(
        cat for cat in CATEGORIES if post.mine[cat].mean - pre.mine[cat].mean > MATERIAL_MEAN_DELTA
    )
    expected_my_loss = tuple(
        cat for cat in CATEGORIES if post.mine[cat].mean - pre.mine[cat].mean < -MATERIAL_MEAN_DELTA
    )
    expected_their_gain = tuple(
        cat
        for cat in CATEGORIES
        if post.theirs[cat].mean - pre.theirs[cat].mean > MATERIAL_MEAN_DELTA
    )
    expected_their_loss = tuple(
        cat
        for cat in CATEGORIES
        if post.theirs[cat].mean - pre.theirs[cat].mean < -MATERIAL_MEAN_DELTA
    )

    assert candidate.my_gain == expected_my_gain
    assert candidate.my_loss == expected_my_loss
    assert candidate.their_gain == expected_their_gain
    assert candidate.their_loss == expected_their_loss


# --- fan-plausibility (mandatory) ------------------------------------------------


def test_center_heavy_team_top_candidate_sends_a_big_and_receives_a_guard():
    # NOTE: an earlier version of this test only asserted that guard1/centerX
    # (structurally excluded by eligibility no matter what the keep-filter
    # does) never appear -- that holds even with the keep-filter replaced by
    # `if True:` or with give-eligibility opened to the whole roster, so it
    # caught nothing. This version pins the actual RECOMMENDATION -- the
    # single top-ranked candidate's exact identity -- which does depend on
    # both the keep-filter and give-eligibility being correct (verified by
    # mutation: both those mutations change the winner, see dispatch notes).
    #
    # mine: 4 real centers (reb/blk surplus, uniform -0.4 ast/tpm drag) plus
    # guard1, a misfit who is NOT part of the reb/blk surplus (so correctly
    # excluded from eligible_give) but is a much bigger ast/tpm drag (-1.0)
    # than any center -- removing him would numerically help my ast/tpm
    # deficit MORE than any legitimate center-for-guard swap, which is
    # exactly the trap give-eligibility exists to prevent.
    mine = [
        _player("center1", reb=1.0, blk=1.0, ast=-0.4, tpm=-0.4),
        _player("center2", reb=0.9, blk=0.9, ast=-0.4, tpm=-0.4),
        _player("center3", reb=0.8, blk=0.8, ast=-0.4, tpm=-0.4),
        _player("center4", reb=0.7, blk=0.7, ast=-0.4, tpm=-0.4),
        _player("guard1", reb=0.0, blk=0.0, ast=-1.0, tpm=-1.0),
    ]
    # theirs: the mirror image -- 4 real guards (ast/tpm surplus) plus
    # centerX, a weak replacement center excluded from eligible_get the same
    # way guard1 is excluded from eligible_give.
    theirs = [
        _player("guardA", ast=1.0, tpm=1.0, reb=-0.4, blk=-0.4),
        _player("guardB", ast=0.9, tpm=0.9, reb=-0.4, blk=-0.4),
        _player("guardC", ast=0.8, tpm=0.8, reb=-0.4, blk=-0.4),
        _player("guardD", ast=0.7, tpm=0.7, reb=-0.4, blk=-0.4),
        _player("guardE", ast=0.6, tpm=0.6, reb=-0.4, blk=-0.4),
        _player("centerX", ast=-0.2, tpm=-0.2, reb=-0.2, blk=-0.2),
    ]
    comparison = compare_rosters(mine, theirs)
    assert set(comparison.my_surplus) == {"reb", "blk"}
    assert set(comparison.their_surplus) == {"ast", "tpm"}

    result = generate_trade_candidates(mine, theirs, comparison=comparison, max_package=2, limit=50)

    assert result.candidates != ()
    top = result.candidates[0]
    # hand/script-verified winner: give center1 (best reb/blk, alphabetical
    # tie-break among the four equally-improving centers) for guardA (their
    # best ast/tpm contributor) -- a genuine big-for-guard trade
    assert top.give == ("center1",)
    assert top.get == ("guardA",)
    assert "guard1" not in top.give
    assert "centerX" not in top.get


# --- ranking never rewards damage over no-damage (C1) ---------------------------


def test_ranking_never_ranks_a_damaging_trade_above_an_undamaged_one():
    # mine punts ast AND stl. give_safe/give_damage both clear the reb
    # surplus bar equally (only reb differs between give options -- ast/tpm
    # are irrelevant to give-side eligibility so they don't bias this). Two
    # 1-for-1 trades, both improving ast by a real amount:
    #   "safe"   (give_safe/get_safe): ast improves, stl untouched.
    #   "damage" (give_damage/get_damage): ast improves LESS than safe's, but
    #            stl is tanked by -3.0 z (get_damage's stl payload).
    # Both trades intersect my_deficit in exactly ast (stl never counts as
    # "improved" in either -- unchanged in safe, a loss in damage), so they
    # tie on deficit-categories-improved and the ranking falls through to the
    # secondary key this test exists to pin: genuine (positive-part) total
    # improvement, NOT abs(). Under abs(), damage's huge negative stl swing
    # counted as "movement" and outranked safe despite doing net harm --
    # exactly the bug the reviewer demonstrated with three steal-tanking
    # trades taking the top three ranks.
    mine = [
        _player("give_safe", reb=1.0),
        _player("give_damage", reb=0.9),
        _player("give_extra1", reb=0.85),
        _player("give_extra2", reb=0.8),
        _player("give_extra3", reb=0.75),
        _player("base1", ast=-1.3, stl=-1.3),
        _player("base2", ast=-1.3, stl=-1.3),
    ]
    theirs = [
        _player("get_safe", ast=1.0, reb=-0.6, stl=0.0),
        _player("get_damage", ast=0.55, reb=-0.6, stl=-3.0),
        _player("get_extra1", ast=0.9, reb=-0.6),
        _player("get_extra2", ast=0.8, reb=-0.6),
        _player("get_extra3", ast=0.7, reb=-0.6),
        _player("tbase1", ast=0.0, reb=0.0),
        _player("tbase2", ast=0.0, reb=0.0),
    ]
    comparison = compare_rosters(mine, theirs)
    assert comparison.my_surplus == ("reb",)
    assert set(comparison.my_deficit) == {"ast", "stl"}

    result = generate_trade_candidates(mine, theirs, comparison=comparison, max_package=1, limit=50)

    safe = next(c for c in result.candidates if c.give == ("give_safe",) and c.get == ("get_safe",))
    damage = next(
        c for c in result.candidates if c.give == ("give_damage",) and c.get == ("get_damage",)
    )
    assert safe.my_gain == ("ast",)
    assert "stl" not in safe.my_gain and "stl" not in safe.my_loss  # untouched, not just small
    assert damage.my_gain == ("ast",)
    assert "stl" in damage.my_loss  # genuinely tanked, not clamped away entirely

    # the pin: the trade that does no collateral damage must never rank
    # behind the one that tanks an unrelated deficit category by the same
    # (or greater) magnitude of harm
    safe_index = result.candidates.index(safe)
    damage_index = result.candidates.index(damage)
    assert safe_index < damage_index


# --- punt awareness (I5) ----------------------------------------------------------


def _punt_ft_fixture():
    # mine punts BOTH ft_pct and blk (de facto weak in build_profile's sense,
    # not necessarily deliberately conceded). All mine give options carry an
    # IDENTICAL ft_pct/blk drag (-0.5 each) so which one is given away never
    # biases either category -- the only thing that moves ft_pct or blk is
    # which THEIRS player is received:
    #   tA carries ft_pct=+0.9 but blk=-0.5 (exactly offsetting -- giving a
    #       -0.5 blk contributor for one with the same -0.5 blk is a wash) --
    #       a trade using tA improves ft_pct ONLY.
    #   tB is the mirror: blk=+0.9, ft_pct=-0.5 (offsetting) -- improves blk
    #       ONLY.
    mine = [
        _player("g1", reb=1.0, ft_pct=-0.5, blk=-0.5),
        _player("g2", reb=0.9, ft_pct=-0.5, blk=-0.5),
        _player("g3", reb=0.8, ft_pct=-0.5, blk=-0.5),
        _player("g4", reb=0.7, ft_pct=-0.5, blk=-0.5),
    ]
    theirs = [
        _player("tA", ast=1.0, reb=-0.4, ft_pct=0.9, blk=-0.5),
        _player("tB", ast=0.9, reb=-0.4, ft_pct=-0.5, blk=0.9),
        _player("tC", ast=0.8, reb=-0.4),
        _player("tD", ast=0.7, reb=-0.4),
    ]
    return mine, theirs


def test_punt_team_is_offered_trades_that_do_not_improve_the_punted_category():
    mine, theirs = _punt_ft_fixture()
    comparison = compare_rosters(mine, theirs)
    assert set(comparison.my_deficit) == {"ft_pct", "blk"}

    # baseline (no punt): a trade that improves ONLY ft_pct is offered, since
    # ft_pct is a genuine (unpunted) deficit here
    baseline = generate_trade_candidates(mine, theirs, comparison=comparison, max_package=1, limit=50)
    ft_only = next(c for c in baseline.candidates if c.give == ("g1",) and c.get == ("tA",))
    assert "ft_pct" in ft_only.my_gain
    assert "blk" not in ft_only.my_gain

    # punting ft_pct: the ft_pct-only trade must now be REJECTED -- it does
    # nothing for the one deficit that still counts (blk) -- while a
    # blk-only trade is still offered, proving the punt team isn't required
    # to fix the category it deliberately conceded
    punted = generate_trade_candidates(
        mine, theirs, comparison=comparison, max_package=1, limit=50, punt=frozenset({"ft_pct"})
    )
    assert not any(c.give == ("g1",) and c.get == ("tA",) for c in punted.candidates)
    blk_only = next(c for c in punted.candidates if c.give == ("g1",) and c.get == ("tB",))
    assert "ft_pct" not in blk_only.my_gain
    assert "blk" in blk_only.my_gain


def test_unknown_punt_category_raises_value_error_naming_it():
    with pytest.raises(ValueError) as exc_info:
        generate_trade_candidates([], [], punt=frozenset({"assists"}))
    assert "assists" in str(exc_info.value)


# --- MATERIAL_MEAN_DELTA suppresses noise (M11) -----------------------------------


def test_material_mean_delta_suppresses_a_small_genuine_move():
    # give1 carries a small blk value (0.03) that no other mine player
    # shares; swapping it out for t1 (blk=0.0, otherwise a plain ast-surplus
    # contributor) moves mine's blk mean by only -0.01 -- real, but far
    # below MATERIAL_MEAN_DELTA (0.05), so it must not appear in my_gain or
    # my_loss. (Zeroing MATERIAL_MEAN_DELTA lets this -0.01 leak into
    # my_loss -- verified by hand against the source, see dispatch report.)
    mine = [
        _player("give1", reb=1.0, ast=-0.4, blk=0.03),
        _player("b2", reb=0.9, ast=-0.4),
        _player("b3", reb=0.8, ast=-0.4),
    ]
    theirs = [
        _player("t1", ast=1.0, reb=-0.4),
        _player("t2", ast=0.9, reb=-0.4),
        _player("t3", ast=0.8, reb=-0.4),
    ]
    comparison = compare_rosters(mine, theirs)

    result = generate_trade_candidates(mine, theirs, comparison=comparison, max_package=1)
    candidate = next(c for c in result.candidates if c.give == ("give1",) and c.get == ("t1",))

    assert "blk" not in candidate.my_gain
    assert "blk" not in candidate.my_loss


# --- bounded evaluation (M12) ------------------------------------------------------


def test_evaluated_combinations_are_bounded_and_reported_as_truncated(monkeypatch):
    # `limit` only caps KEPT candidates -- worst case, evaluation itself is
    # unbounded (C(13,2)^2 for two 13-man rosters at max_package=2). Patch
    # MAX_EVALUATED down to something smaller than this fixture's 9 possible
    # combinations so the ceiling -- not `limit` -- is what stops the search.
    import ninecat.engine.trade_candidates as trade_candidates_module

    monkeypatch.setattr(trade_candidates_module, "MAX_EVALUATED", 5)
    mine, theirs = _headline_rosters()

    result = generate_trade_candidates(mine, theirs, max_package=1, limit=50)

    assert result.evaluated == 5
    assert result.truncated is True


# --- determinism ---------------------------------------------------------------


def test_same_inputs_give_identical_ordering():
    mine, theirs = _headline_rosters()

    first = generate_trade_candidates(mine, theirs, max_package=2)
    second = generate_trade_candidates(mine, theirs, max_package=2)

    assert first == second


def test_precomputed_comparison_matches_default_internal_computation():
    mine, theirs = _headline_rosters()
    comparison = compare_rosters(mine, theirs)

    with_default = generate_trade_candidates(mine, theirs)
    with_precomputed = generate_trade_candidates(mine, theirs, comparison=comparison)

    assert with_default == with_precomputed


# --- degenerate inputs -----------------------------------------------------------


def test_empty_rosters_return_empty_candidate_set_not_an_exception():
    result = generate_trade_candidates([], [])

    assert result == CandidateSet(candidates=(), evaluated=0, truncated=False)


def test_no_surplus_on_either_side_returns_empty_candidate_set():
    # every category "average" -> no surplus, no deficit anywhere
    mine = [_player("m1"), _player("m2")]
    theirs = [_player("t1"), _player("t2")]

    result = generate_trade_candidates(mine, theirs)

    assert result.candidates == ()
    assert result.evaluated == 0
    assert result.truncated is False


# --- validation ------------------------------------------------------------------


def test_player_on_both_rosters_raises_value_error_naming_the_key():
    shared = _player("shared_player", reb=1.0)
    mine = [shared]
    theirs = [shared]

    with pytest.raises(ValueError) as exc_info:
        generate_trade_candidates(mine, theirs)
    assert "shared_player" in str(exc_info.value)


@pytest.mark.parametrize("bad_max_package", [0, -1, 3, 10])
def test_invalid_max_package_raises_value_error(bad_max_package):
    with pytest.raises(ValueError):
        generate_trade_candidates([], [], max_package=bad_max_package)


@pytest.mark.parametrize("bad_limit", [0, -1, -25])
def test_invalid_limit_raises_value_error(bad_limit):
    with pytest.raises(ValueError):
        generate_trade_candidates([], [], limit=bad_limit)
