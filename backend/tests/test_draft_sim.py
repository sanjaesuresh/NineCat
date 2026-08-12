import pytest

from ninecat.engine.draft import DraftPoolPlayer, LeagueConfig
from ninecat.engine.draft_sim import (
    DraftResult,
    PickRecommendation,
    picks_until_next_turn,
    recommend_picks,
    simulate_draft,
    snake_order,
)
from ninecat.engine.zscores import CATEGORIES

# solo-UTIL config used throughout: no positional scarcity noise, so ranking
# math is driven purely by base z-sum against a single shared replacement
SOLO_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("UTIL", 1),))


def _z(**overrides: float) -> dict[str, float]:
    """All nine categories default to 0.0; pass only the ones a hand-computed
    case cares about, so the rest can't silently pollute the base sum."""
    z = {c: 0.0 for c in CATEGORIES}
    z.update(overrides)
    return z


def _player(key: str, position: str | None = None, games: float = 82.0, **overrides: float) -> DraftPoolPlayer:
    return DraftPoolPlayer(player_key=key, position=position, projected_games=games, zscores=_z(**overrides))


# --- snake_order --------------------------------------------------------------


def test_snake_order_reverses_even_rounds():
    # 4 teams, 3 rounds: round1 forward, round2 reversed, round3 forward
    assert snake_order(4, 3) == (1, 2, 3, 4, 4, 3, 2, 1, 1, 2, 3, 4)


def test_snake_order_single_round_is_forward():
    assert snake_order(6, 1) == (1, 2, 3, 4, 5, 6)


# --- picks_until_next_turn: odd round -> even round boundary ------------------


def test_picks_until_next_turn_odd_to_even_boundary():
    # 10-team league, picking at the end of round 1 (odd), turning into
    # round 2 (reversed). Hand-derived from the overall draft order:
    #   round1: picks 1..10 = teams 1..10
    #   round2 (reversed): picks 11..20 = teams 10..1
    # slot 1 (first pick, overall=1): next pick is team1 at overall=20 -> 18 opponent picks (2..19)
    assert picks_until_next_turn(1, 10) == 18
    # slot 10 (last pick, overall=10): next pick is team10 at overall=11 -> back-to-back, 0 opponent picks
    assert picks_until_next_turn(10, 10) == 0
    # slot 5 (middle, overall=5): next pick is team5 at overall=16 (6th pick of round2) -> picks 6..15 = 10
    assert picks_until_next_turn(5, 10) == 10


# --- picks_until_next_turn: even round -> odd round boundary ------------------


def test_picks_until_next_turn_even_to_odd_boundary():
    # same 10-team league, now picking at the end of round 2 (even, reversed),
    # turning into round 3 (forward again):
    #   round2 (reversed): picks 11..20 = teams 10..1
    #   round3: picks 21..30 = teams 1..10
    # team1 picks last in round2 (overall=20) and first in round3 (overall=21) -> 0 opponent picks
    assert picks_until_next_turn(20, 10) == 0
    # team10 picks first in round2 (overall=11) and last in round3 (overall=30) -> picks 12..29 = 18
    assert picks_until_next_turn(11, 10) == 18
    # team5 picks 6th in round2 (overall=16) and 5th in round3 (overall=25) -> picks 17..24 = 8
    assert picks_until_next_turn(16, 10) == 8


# --- recommend_picks: empty roster --------------------------------------------


def test_empty_roster_is_pure_value_ranking_with_best_available_reason():
    # 3 players, distinct pts z, position=None (UTIL only), 1-team pool so
    # demand=1 -> replacement = 2nd-best base (index 1, base=1.0):
    #   p_high: base=3.0 -> vorp=2.0 -> value=2.0
    #   p_mid:  base=1.0 -> vorp=0.0 -> value=0.0
    #   p_low:  base=-1.0 -> vorp=-2.0 -> value=-2.0
    # empty roster -> every need weight is 0, so rank_score == value exactly,
    # and no need-fit reason can ever fire -> "Best player available" for all
    p_high = _player("high", pts=3.0)
    p_mid = _player("mid", pts=1.0)
    p_low = _player("low", pts=-1.0)

    recs = recommend_picks([], [p_high, p_mid, p_low], SOLO_CONFIG, overall_pick=1)

    assert [r.player_key for r in recs] == ["high", "mid", "low"]
    assert recs[0].value == pytest.approx(2.0)
    assert recs[0].rank_score == pytest.approx(2.0)
    assert recs[1].value == pytest.approx(0.0)
    assert recs[2].value == pytest.approx(-2.0)
    assert all(r.reasons == ("Best player available",) for r in recs)


# --- recommend_picks: need-weighted flip ---------------------------------------


def test_need_weighted_rank_score_promotes_rebounder_over_higher_value_guard():
    # my roster: reb mean = -1.0 <= -0.35 -> w_reb = 0.5; every other category
    # means 0.0 -> weight 0
    #
    # guard: pts=1.0, reb=0.0 -> base=1.0
    # rebounder: pts=-0.5, reb=1.2 -> base=0.7
    # only 2 players -> demand=1 -> replacement = 2nd-best base = 0.7 (shared,
    # same UTIL class for both) -> vorp/value:
    #   guard:      vorp=1.0-0.7=0.3 -> value=0.3
    #   rebounder:  vorp=0.7-0.7=0.0 -> value=0.0
    # so on raw value the guard is ahead (0.3 > 0.0) -- but the need bonus:
    #   guard's rank_score      = 0.3 + 0.0*0.5      = 0.3  (reb z=0.0, no bonus)
    #   rebounder's rank_score  = 0.0 + 1.2*0.5       = 0.6
    # flips the order: rebounder ranks first despite the lower raw value
    me = _player("me", reb=-1.0)
    guard = _player("guard", pts=1.0, reb=0.0)
    rebounder = _player("rebounder", pts=-0.5, reb=1.2)

    recs = recommend_picks([me], [guard, rebounder], SOLO_CONFIG, overall_pick=1)
    by_key = {r.player_key: r for r in recs}

    assert by_key["guard"].value == pytest.approx(0.3)
    assert by_key["rebounder"].value == pytest.approx(0.0)
    assert by_key["guard"].rank_score == pytest.approx(0.3)
    assert by_key["rebounder"].rank_score == pytest.approx(0.6)
    assert [r.player_key for r in recs] == ["rebounder", "guard"]


# --- recommend_picks: a center is never recommended for an assists need -------


def test_center_with_low_ast_gets_no_assists_need_reason():
    # roster ast mean = -1.0 <= -0.35 -> w_ast = 0.5 (a real, strong need) --
    # but the available big's own ast z (0.2) is well below the 0.5 fill
    # threshold, so the reason must never claim it fills that need
    me = _player("me", ast=-1.0)
    big = _player("big", position="C", ast=0.2, reb=1.0, blk=1.0)

    recs = recommend_picks([me], [big], SOLO_CONFIG, overall_pick=1)

    assert "Fills your AST need" not in recs[0].reasons
    assert "ast" not in recs[0].need_cats


# --- recommend_picks: a positive need-fit reason actually fires ----------------


def test_fills_need_reason_and_need_cats_fire_for_a_qualifying_category():
    # roster reb mean = -1.0 <= -0.35 -> w_reb = 0.5; candidate's own reb z
    # (0.6) clears the 0.5 fill threshold -> both the rendered reason string
    # and the raw contract-key need_cats field must reflect it
    me = _player("me", reb=-1.0)
    rebounder = _player("rebounder", reb=0.6)

    recs = recommend_picks([me], [rebounder], SOLO_CONFIG, overall_pick=1)

    assert "Fills your REB need" in recs[0].reasons
    assert recs[0].need_cats == ("reb",)


def test_fills_need_reasons_cap_at_two_in_canonical_order():
    # roster is needy in reb, ast, and stl (all mean=-1.0 -> weight 0.5) --
    # a candidate qualifying (z >= 0.5) in all three must only ever surface
    # the first 2 in CATEGORIES order (reb, then ast); stl is dropped even
    # though it independently qualifies, per the "up to 2" cap
    me = _player("me", reb=-1.0, ast=-1.0, stl=-1.0)
    triple_threat = _player("triple", reb=1.0, ast=1.0, stl=1.0)

    recs = recommend_picks([me], [triple_threat], SOLO_CONFIG, overall_pick=1)

    assert recs[0].need_cats == ("reb", "ast")
    assert recs[0].reasons[:2] == ("Fills your REB need", "Fills your AST need")
    assert "Fills your STL need" not in recs[0].reasons


# --- recommend_picks: need-weight tiers (0.5 / 0.25 / 0) and the -0.35 boundary -


def test_need_weight_tiers_and_minus_0_35_boundary_are_pinned():
    # single-player roster -> roster mean == that player's own z per category:
    #   reb = -0.35 (<=-0.35)          -> w_reb = 0.5  (boundary is INCLUSIVE)
    #   ast = -0.34 (-0.35 < . < 0)    -> w_ast = 0.25
    #   stl =  0.0  (not < 0)          -> w_stl = 0.0
    #
    # 3 candidates, each isolated to one of those categories at z=1.0, all
    # other cats 0.0 -> identical base=1.0 for each -> with SOLO_CONFIG's
    # 1-team/1-UTIL-slot demand=1, replacement = 2nd-best of 3 tied bases
    # (1.0) -> vorp=0.0 -> value=0.0 for every candidate, so rank_score is
    # driven ENTIRELY by the need bonus, isolating each weight tier exactly:
    #   reb_candidate: rank_score = 0.0 + 1.0*0.5  = 0.5
    #   ast_candidate: rank_score = 0.0 + 1.0*0.25 = 0.25
    #   stl_candidate: rank_score = 0.0 + 1.0*0.0  = 0.0
    me = _player("me", reb=-0.35, ast=-0.34, stl=0.0)
    reb_candidate = _player("reb_c", reb=1.0)
    ast_candidate = _player("ast_c", ast=1.0)
    stl_candidate = _player("stl_c", stl=1.0)

    recs = recommend_picks(
        [me], [reb_candidate, ast_candidate, stl_candidate], SOLO_CONFIG, overall_pick=1
    )
    by_key = {r.player_key: r for r in recs}

    assert by_key["reb_c"].rank_score == pytest.approx(0.5)
    assert by_key["ast_c"].rank_score == pytest.approx(0.25)
    assert by_key["stl_c"].rank_score == pytest.approx(0.0)
    assert [r.player_key for r in recs] == ["reb_c", "ast_c", "stl_c"]
    assert by_key["reb_c"].need_cats == ("reb",)
    assert by_key["ast_c"].need_cats == ("ast",)
    assert by_key["stl_c"].need_cats == ()  # weight 0 -> never a "need" regardless of z


# --- recommend_picks: punt zeroes the need weight, not just the base sum -------


def test_punt_zeroes_need_weight_and_suppresses_its_need_reason():
    # roster reb mean = -1.0 -> without punt this is a strong (0.5-weight)
    # need; WITH punt={"reb"}, _need_weights must force it to 0 regardless
    # of the roster mean, and compute_draft_values must also drop reb from
    # the base sum it feeds recommend_picks.
    #
    # p1: pts=1.0, reb=0.0 -> base(punt reb)=1.0
    # p2: pts=0.5, reb=2.0 -> base(punt reb)=0.5  (reb excluded from the sum)
    # 2 players -> demand=1 -> replacement=2nd-best base=0.5 (shared) ->
    #   p1: vorp=1.0-0.5=0.5 -> value=0.5
    #   p2: vorp=0.5-0.5=0.0 -> value=0.0
    # with the reb weight forced to 0, p2's huge reb z earns no bonus at all,
    # so ranking is pure value -> p1 first, no flip (contrast with the
    # unpunted need-weighted-flip test above, where p2 would have won)
    me = _player("me", reb=-1.0)
    p1 = _player("p1", pts=1.0, reb=0.0)
    p2 = _player("p2", pts=0.5, reb=2.0)

    recs = recommend_picks([me], [p1, p2], SOLO_CONFIG, overall_pick=1, punt=frozenset({"reb"}))
    by_key = {r.player_key: r for r in recs}

    assert by_key["p1"].value == pytest.approx(0.5)
    assert by_key["p2"].value == pytest.approx(0.0)
    assert by_key["p1"].rank_score == pytest.approx(0.5)
    assert by_key["p2"].rank_score == pytest.approx(0.0)
    assert [r.player_key for r in recs] == ["p1", "p2"]
    assert "Fills your REB need" not in by_key["p2"].reasons
    assert by_key["p2"].need_cats == ()


# --- recommend_picks: limit is respected ---------------------------------------


def test_limit_caps_returned_recommendations():
    players = [_player(f"p{i}", pts=float(i)) for i in range(5)]
    recs = recommend_picks([], players, SOLO_CONFIG, overall_pick=1, limit=2)
    assert len(recs) == 2
    # still the top-2 by value, in order
    assert [r.player_key for r in recs] == ["p4", "p3"]


# --- recommend_picks: injury-risk reason threshold -----------------------------


def test_injury_risk_reason_fires_strictly_below_games_factor_threshold():
    # games_factor = projected_games / 82; threshold is a strict "< 0.75"
    at_boundary = _player("boundary", games=61.5)  # 61.5/82 == 0.75 exactly -> no reason
    below = _player("below", games=61.0)  # 61/82 ~= 0.7439 < 0.75 -> reason fires

    recs = recommend_picks([], [at_boundary, below], SOLO_CONFIG, overall_pick=1)
    by_key = {r.player_key: r for r in recs}

    assert not any(r.startswith("Injury risk") for r in by_key["boundary"].reasons)
    assert "Injury risk: 61 games" in by_key["below"].reasons


def test_injury_risk_reason_truncates_games_not_rounds():
    # 60.6/82 ~= 0.739 < 0.75 -> reason fires; int(60.6) == 60, not round(60.6) == 61
    # -- pins truncation, not rounding
    player = _player("frail", games=60.6)
    recs = recommend_picks([], [player], SOLO_CONFIG, overall_pick=1)
    assert "Injury risk: 60 games" in recs[0].reasons


# --- recommend_picks: scarcity-urgency reason, comparable-or-better counts ----
#
# C2 review finding: the original rule counted every positive-value player at
# a class (regardless of how they compared to the specific candidate), which
# fired on ~all 72 players of a real seeded pool at pick 1, including the
# consensus #1 overall -- meaningless spam. The fix scopes the count to only
# players AT LEAST AS GOOD as the candidate itself ("comparable-or-better"),
# so it only fires for someone actually at risk of losing their tier, not
# every player in a merely-not-terrible position.
#
# The two cases below are deliberately two separate calls/configs: this count
# is monotonically non-decreasing as a candidate's own value drops (a lower-
# value candidate's ">=" threshold is strictly less selective, so its count
# can only be >= a higher-value candidate's, for any FIXED picks_left). That
# makes "top-of-class never fires, marginal always fires, same call" a
# mathematical impossibility -- so each case pins its own picks_left instead.


def test_scarcity_reason_does_not_fire_for_a_lone_top_of_class_player():
    # single "C" player, 10-team league, overall_pick=10 -> picks_left=0
    # (picks_until_next_turn(10, 10) == 0, the back-to-back turn case).
    # He's the only player in his class -> comparable-or-better count = 1
    # (himself) -> 1 <= 0 is False -> no fire, even though he's trivially
    # "top of class" (nothing else to compare him to)
    config = LeagueConfig(num_teams=10, roster_slots=(("C", 2),))
    only_center = _player("only_center", position="C", pts=5.0)

    recs = recommend_picks([], [only_center], config, overall_pick=10)

    assert "May not last until your next pick" not in recs[0].reasons


def test_scarcity_reason_fires_for_a_marginal_mid_tier_player():
    # a 5-deep "PG" class with distinct values 10/8/6/4/2 (via pts z; base ==
    # pts here since no other cat is set). 6-team league, overall_pick=4 ->
    # picks_left = picks_until_next_turn(4, 6) = 4 (round1, slot4 (odd) ->
    # next_overall = 1*6 + (6-4+1) = 9 -> picks_left = 9-4-1 = 4).
    # demand("PG") = ceil(6*1) = 6 -> replacement = 5th-best (index
    # min(6,4)=4) = value 2 (the weakest) -> vorp/value = raw pts - 2:
    #   [8, 6, 4, 2, 0] for pts [10, 8, 6, 4, 2] respectively.
    # "marginal" = the pts=6 player (value=4, the 3rd-best): comparable-or-
    # better count (value >= 4) = {8, 6, 4} = 3 -> 3 <= picks_left(4) -> fires
    config = LeagueConfig(num_teams=6, roster_slots=(("PG", 1),))
    players = [_player(f"pg{v}", position="PG", pts=float(v)) for v in (10, 8, 6, 4, 2)]

    recs = recommend_picks([], players, config, overall_pick=4)
    by_key = {r.player_key: r for r in recs}

    assert "May not last until your next pick" in by_key["pg6"].reasons


# --- dataclass sanity ------------------------------------------------------


def test_pickrecommendation_is_frozen_dataclass():
    rec = PickRecommendation(
        player_key="x", value=1.0, rank_score=1.0, reasons=("Best player available",), need_cats=()
    )
    with pytest.raises(Exception):
        rec.value = 2.0  # type: ignore[misc]


def test_draftresult_is_frozen_dataclass():
    result = DraftResult(picks=((1, 1, "x"),), my_roster=("x",))
    with pytest.raises(Exception):
        result.my_roster = ("y",)  # type: ignore[misc]


# --- simulate_draft: seeded determinism ----------------------------------------

# 24 distinct UTIL-only players, enough for a 4-team/3-round (12-pick) mock draft
_SIM_POOL = [_player(f"p{i}", pts=float(i)) for i in range(1, 25)]
_SIM_CONFIG = LeagueConfig(num_teams=4, roster_slots=(("UTIL", 1),))


def test_simulate_draft_same_seed_reproduces_identical_result():
    a = simulate_draft(_SIM_POOL, _SIM_CONFIG, my_slot=2, rounds=3, seed=42)
    b = simulate_draft(_SIM_POOL, _SIM_CONFIG, my_slot=2, rounds=3, seed=42)
    assert a == b


def test_simulate_draft_different_seed_diverges():
    a = simulate_draft(_SIM_POOL, _SIM_CONFIG, my_slot=2, rounds=3, seed=42)
    c = simulate_draft(_SIM_POOL, _SIM_CONFIG, my_slot=2, rounds=3, seed=7)
    assert a != c


def test_simulate_draft_my_roster_matches_my_snake_slots():
    result = simulate_draft(_SIM_POOL, _SIM_CONFIG, my_slot=2, rounds=3, seed=42)
    expected = tuple(pk for (_overall, team, pk) in result.picks if team == 2)
    assert result.my_roster == expected
    assert len(result.picks) == 3 * 4
    assert len(result.my_roster) == 3


# --- simulate_draft: loud guard on an undersized pool (C1) ---------------------


def test_simulate_draft_raises_on_pool_smaller_than_teams_times_rounds():
    # 4 teams x 3 rounds needs 12 players; only give it 5 -> must raise
    # loudly (not silently truncate the draft) and name both numbers
    small_pool = _SIM_POOL[:5]
    with pytest.raises(ValueError, match=r"\b5\b.*\b12\b"):
        simulate_draft(small_pool, _SIM_CONFIG, my_slot=2, rounds=3, seed=42)


# --- simulate_draft: adp must exactly match the pool's keys (C5) ---------------


def test_simulate_draft_raises_when_adp_is_missing_a_pool_player():
    config = LeagueConfig(num_teams=2, roster_slots=(("UTIL", 1),))
    pool = [_player("p1", pts=2.0), _player("p2", pts=1.0)]
    with pytest.raises(ValueError):
        simulate_draft(pool, config, my_slot=1, rounds=1, seed=1, adp=["p1"])  # missing p2


def test_simulate_draft_raises_when_adp_has_a_phantom_player_not_in_pool():
    config = LeagueConfig(num_teams=2, roster_slots=(("UTIL", 1),))
    pool = [_player("p1", pts=2.0), _player("p2", pts=1.0)]
    with pytest.raises(ValueError):
        simulate_draft(pool, config, my_slot=1, rounds=1, seed=1, adp=["p1", "p2", "ghost"])


# --- simulate_draft: an explicit adp argument is actually honored --------------


def test_simulate_draft_explicit_adp_changes_opponent_picks_vs_default():
    # my pick (team 1) always uses recommend_picks over raw value, so it's
    # identical either way (p1, highest value); the opponent's (team 2) pick
    # is drawn from the weighted top of remaining ADP, which differs sharply
    # between the default (value-desc) order and a fully reversed explicit
    # order -> the two results must diverge
    config = LeagueConfig(num_teams=2, roster_slots=(("UTIL", 1),))
    pool = [_player(f"p{i}", pts=float(i)) for i in range(1, 5)]  # p4 > p3 > p2 > p1 by value
    default_result = simulate_draft(pool, config, my_slot=1, rounds=2, seed=3)

    reversed_adp = ["p1", "p2", "p3", "p4"]  # worst-to-best, opposite of the default ordering
    custom_result = simulate_draft(pool, config, my_slot=1, rounds=2, seed=3, adp=reversed_adp)

    assert default_result != custom_result
