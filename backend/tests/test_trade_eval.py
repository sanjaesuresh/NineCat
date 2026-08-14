import pytest

from ninecat.engine.build_profile import compute_team_profile
from ninecat.engine.draft import DEFAULT_ROSTER_SLOTS, LeagueConfig
from ninecat.engine.roster_compare import RosterPlayer
from ninecat.engine.trade_candidates import TradeCandidate
from ninecat.engine.trade_eval import (
    BALANCED_NET_VALUE,
    SideOutcome,
    TradeVerdict,
    evaluate_trade,
    evaluate_trades,
)
from ninecat.engine.zscores import CATEGORIES

TOL = 1e-6


def _zero_cats(**overrides):
    # mirrors test_trade_candidates.py's helper: full 9-cat dict, defaulted to
    # 0.0, only the categories under test overridden
    base = {cat: 0.0 for cat in CATEGORIES}
    base.update(overrides)
    return base


def _player(key, **overrides):
    return RosterPlayer(player_key=key, zscores=_zero_cats(**overrides))


def _candidate(give, get, **kwargs):
    # evaluate_trade recomputes real post-trade gain/loss itself and never
    # reads TradeCandidate's own *_gain/*_loss fields, so these are left
    # empty by default in tests that construct a candidate directly
    defaults = dict(my_gain=(), my_loss=(), their_gain=(), their_loss=())
    defaults.update(kwargs)
    return TradeCandidate(give=give, get=get, **defaults)


# --- before/after profiles are internally consistent ----------------------


def test_before_after_profiles_match_independently_swapped_roster():
    # 2-for-2 package, exercised deliberately so the swap logic is proven
    # correct for more than the trivial 1-for-1 case
    mine = [
        _player("m1", reb=0.8, ast=-0.4),
        _player("m2", reb=0.7, ast=-0.4),
        _player("m3", pts=0.2),
    ]
    theirs = [
        _player("t1", ast=0.9, reb=-0.4),
        _player("t2", ast=0.8, reb=-0.4),
        _player("t3", stl=0.3),
    ]
    candidate = _candidate(give=("m1", "m2"), get=("t1", "t2"))

    result = evaluate_trade(candidate, mine, theirs)

    # independently swap by hand and recompute compute_team_profile directly
    # -- the cheap strong guard that the whole module isn't subtly wrong
    expected_new_mine = compute_team_profile(
        [dict(p.zscores) for p in (mine[2], theirs[0], theirs[1])]
    )
    expected_new_theirs = compute_team_profile(
        [dict(p.zscores) for p in (theirs[2], mine[0], mine[1])]
    )
    assert result.mine.after == expected_new_mine
    assert result.theirs.after == expected_new_theirs
    # before is just the untouched pre-trade profile of each side
    assert result.mine.before == compute_team_profile([dict(p.zscores) for p in mine])
    assert result.theirs.before == compute_team_profile([dict(p.zscores) for p in theirs])


# --- collapse forces rejection regardless of value -------------------------


def test_collapsing_my_strong_category_is_rejected_even_with_positive_net_value():
    # m1 is the SOLE positive blk contributor: blk total 1.9-0.1-0.1=1.7,
    # mean 1.7/3=0.5667 -> "strong". ast: mean -0.4 -> "punt".
    mine = [
        _player("m1", blk=1.9, ast=-0.4),
        _player("m2", reb=0.1, blk=-0.1, ast=-0.4),
        _player("m3", reb=0.1, blk=-0.1, ast=-0.4),
    ]
    # t_big carries a large pts total (3.0) and nothing in blk/ast -- its raw
    # value is high enough to make net_value positive on its own, testing
    # that value alone can't rescue a collapse
    theirs = [_player("t_big", pts=3.0)]

    candidate = _candidate(give=("m1",), get=("t_big",))

    result = evaluate_trade(candidate, mine, theirs)

    # post-trade mine = [m2, m3, t_big]: blk = -0.1-0.1+0 = -0.2, mean
    # -0.0667 -> "average" (was "strong") -> collapse
    assert result.mine.collapsed == ("blk",)
    # net_value = t_big total (3.0) - m1 total (1.9 + -0.4 = 1.5) = 1.5,
    # comfortably above BALANCED_NET_VALUE, yet must still be rejected
    assert result.net_value == pytest.approx(1.5, abs=TOL)
    assert result.net_value > BALANCED_NET_VALUE
    assert result.verdict == "rejected"
    assert "collapsed:blk" in result.reasons
    assert "rejected" in result.reasons


# --- downside is always named -----------------------------------------------


def test_no_downside_token_present_when_nothing_material_is_lost():
    # give1 is an all-zero player -- removing it changes nothing negatively.
    # get1 only adds positive amounts, so no category can decrease.
    mine = [_player("keep1", reb=0.4), _player("give1")]
    theirs = [_player("get1", reb=0.6, ast=0.6)]
    candidate = _candidate(give=("give1",), get=("get1",))

    result = evaluate_trade(candidate, mine, theirs)

    assert result.mine.lost == ()
    assert result.mine.collapsed == ()
    assert "no_downside" in result.reasons
    assert not any(r.startswith("lost:") for r in result.reasons)
    assert not any(r.startswith("collapsed:") for r in result.reasons)


def test_no_downside_token_absent_when_something_material_is_lost():
    mine = [_player("keep1", reb=0.4), _player("give1", ast=0.6)]
    theirs = [_player("get1")]  # all-zero: taking it strictly worsens ast
    candidate = _candidate(give=("give1",), get=("get1",))

    result = evaluate_trade(candidate, mine, theirs)

    assert "ast" in result.mine.lost
    assert "no_downside" not in result.reasons


# --- net_value sign drives the verdict, at the BALANCED_NET_VALUE boundary -


def _boundary_case(get_pts: float):
    # single-player, single-category swap: mine's "give" player contributes
    # 0 everywhere, so net_value collapses to exactly get_pts (see module
    # docstring: for a same-size swap, net_value = incoming total - outgoing
    # total when only the swapped players differ)
    mine = [_player("keep1"), _player("give1")]
    theirs = [_player("get1", pts=get_pts)]
    candidate = _candidate(give=("give1",), get=("get1",))
    return candidate, mine, theirs


def test_net_value_exactly_at_positive_boundary_is_balanced():
    assert BALANCED_NET_VALUE == 0.5
    candidate, mine, theirs = _boundary_case(0.5)

    result = evaluate_trade(candidate, mine, theirs)

    assert result.net_value == pytest.approx(0.5, abs=TOL)
    assert result.verdict == "balanced"


def test_net_value_just_above_positive_boundary_favors_me():
    candidate, mine, theirs = _boundary_case(0.51)

    result = evaluate_trade(candidate, mine, theirs)

    assert result.net_value == pytest.approx(0.51, abs=TOL)
    assert result.verdict == "favors_me"


def test_net_value_exactly_at_negative_boundary_is_balanced():
    candidate, mine, theirs = _boundary_case(-0.5)

    result = evaluate_trade(candidate, mine, theirs)

    assert result.net_value == pytest.approx(-0.5, abs=TOL)
    assert result.verdict == "balanced"


def test_net_value_just_below_negative_boundary_favors_them():
    candidate, mine, theirs = _boundary_case(-0.51)

    result = evaluate_trade(candidate, mine, theirs)

    assert result.net_value == pytest.approx(-0.51, abs=TOL)
    assert result.verdict == "favors_them"


# --- fan-plausibility (mandatory) -------------------------------------------


def test_center_heavy_team_trading_a_guard_for_a_center_is_bad_for_them():
    # mine: deep at center-flavored categories (reb/blk), thin at guard-
    # flavored ones (ast/tpm). g1 is the one "guard" mine has to offer.
    mine = [
        _player("c1", reb=1.0, blk=1.0, ast=-0.4, tpm=-0.4),
        _player("c2", reb=0.9, blk=0.8, ast=-0.4, tpm=-0.4),
        _player("c3", reb=0.8, blk=0.9, ast=-0.4, tpm=-0.4),
        _player("g1", reb=-0.2, blk=-0.2, ast=-0.3, tpm=-0.25),
    ]
    # theirs: the mirror image, deep at ast/tpm, thin at reb/blk. cx is their
    # weak "center" -- barely positive reb/blk, badly negative ast/tpm.
    theirs = [
        _player("t1", ast=1.0, tpm=1.0, reb=-0.4, blk=-0.4),
        _player("t2", ast=0.9, tpm=0.8, reb=-0.4, blk=-0.4),
        _player("t3", ast=0.85, tpm=0.9, reb=-0.4, blk=-0.4),
        _player("cx", reb=0.05, blk=0.05, ast=-0.9, tpm=-0.8),
    ]
    # mine pre: reb (1.0+0.9+0.8-0.2)/4=0.625 strong; blk (1.0+0.8+0.9-0.2)/4
    # =0.625 strong; ast (-0.4*3-0.3)/4=-0.375 punt; tpm (-0.4*3-0.25)/4=
    # -0.3625 punt
    pre = compute_team_profile([dict(p.zscores) for p in mine])
    assert pre["labels"]["reb"] == "strong"
    assert pre["labels"]["blk"] == "strong"
    assert pre["labels"]["ast"] == "punt"
    assert pre["labels"]["tpm"] == "punt"

    # the backwards trade: I send out my one guard, I receive their weak
    # center -- exactly what the plan says must never read as good for me
    candidate = _candidate(give=("g1",), get=("cx",))

    result = evaluate_trade(candidate, mine, theirs)

    # net_value = cx total (0.05+0.05-0.9-0.8=-1.6) - g1 total
    # (-0.2-0.2-0.3-0.25=-0.95) = -0.65
    assert result.net_value == pytest.approx(-0.65, abs=TOL)
    assert result.verdict == "favors_them"
    # the downside is named: my already-thin guard categories get worse
    assert "ast" in result.mine.lost
    assert "tpm" in result.mine.lost
    assert "no_downside" not in result.reasons


# --- validation --------------------------------------------------------------


def test_give_player_not_on_mine_raises_value_error_naming_the_key():
    mine = [_player("m1")]
    theirs = [_player("t1")]
    candidate = _candidate(give=("ghost",), get=("t1",))

    with pytest.raises(ValueError) as exc_info:
        evaluate_trade(candidate, mine, theirs)
    assert "ghost" in str(exc_info.value)


def test_get_player_not_on_theirs_raises_value_error_naming_the_key():
    mine = [_player("m1")]
    theirs = [_player("t1")]
    candidate = _candidate(give=("m1",), get=("ghost",))

    with pytest.raises(ValueError) as exc_info:
        evaluate_trade(candidate, mine, theirs)
    assert "ghost" in str(exc_info.value)


def test_evaluate_trades_invalid_limit_raises_value_error():
    with pytest.raises(ValueError):
        evaluate_trades([], [], [], limit=0)


# --- config default ------------------------------------------------------------


def test_config_none_builds_default_and_does_not_raise():
    mine = [_player("m1", reb=0.4), _player("give1")]
    theirs = [_player("get1", reb=0.6)]
    candidate = _candidate(give=("give1",), get=("get1",))

    default_config = LeagueConfig(num_teams=12, roster_slots=DEFAULT_ROSTER_SLOTS)
    with_none = evaluate_trade(candidate, mine, theirs, config=None)
    with_explicit_default = evaluate_trade(candidate, mine, theirs, config=default_config)

    assert with_none == with_explicit_default


# --- determinism ---------------------------------------------------------------


def test_same_inputs_give_identical_result():
    mine = [_player("m1", reb=0.4), _player("give1")]
    theirs = [_player("get1", reb=0.6, ast=0.6)]
    candidate = _candidate(give=("give1",), get=("get1",))

    first = evaluate_trade(candidate, mine, theirs)
    second = evaluate_trade(candidate, mine, theirs)

    assert first == second


# --- evaluate_trades: ordering and limit ----------------------------------------


def test_evaluate_trades_orders_best_for_me_first_with_deterministic_tie_break():
    mine = [_player("keep1"), _player("gA"), _player("gB")]
    theirs = [
        _player("t1", pts=1.0),
        _player("t2", pts=1.0),
        _player("t3", pts=0.2),
    ]
    # c1 and c2 tie on net_value (both 1.0); tie-break must fall to give
    # tuple order ("gA" < "gB") -- c1 before c2. c3 (0.2) sorts last.
    c1 = _candidate(give=("gA",), get=("t1",))
    c2 = _candidate(give=("gB",), get=("t2",))
    c3 = _candidate(give=("gA",), get=("t3",))

    result = evaluate_trades([c3, c2, c1], mine, theirs)

    assert [(v.candidate.give, v.candidate.get) for v in result] == [
        (("gA",), ("t1",)),
        (("gB",), ("t2",)),
        (("gA",), ("t3",)),
    ]
    assert result[0].net_value == pytest.approx(1.0, abs=TOL)
    assert result[2].net_value == pytest.approx(0.2, abs=TOL)


def test_evaluate_trades_respects_limit():
    mine = [_player("keep1"), _player("gA"), _player("gB")]
    theirs = [_player("t1", pts=1.0), _player("t2", pts=0.9)]
    c1 = _candidate(give=("gA",), get=("t1",))
    c2 = _candidate(give=("gB",), get=("t2",))

    result = evaluate_trades([c1, c2], mine, theirs, limit=1)

    assert len(result) == 1
    assert result[0].candidate.give == ("gA",)


# --- dataclass shape sanity ------------------------------------------------------


def test_side_outcome_and_trade_verdict_are_frozen_dataclasses():
    mine = [_player("m1")]
    theirs = [_player("t1")]
    candidate = _candidate(give=("m1",), get=("t1",))

    result = evaluate_trade(candidate, mine, theirs)

    assert isinstance(result, TradeVerdict)
    assert isinstance(result.mine, SideOutcome)
    assert isinstance(result.theirs, SideOutcome)
    with pytest.raises(AttributeError):
        result.net_value = 100.0  # frozen -- must not be mutable
