import os
import subprocess
import sys
from pathlib import Path

import pytest

from ninecat.engine.draft import (
    DEFAULT_ROSTER_SLOTS,
    DraftPoolPlayer,
    LeagueConfig,
    compute_draft_values,
)
from ninecat.engine.zscores import CATEGORIES

TOL = 1e-3


def _z(**overrides: float) -> dict[str, float]:
    """All nine categories default to 0.0; pass only the ones a hand-computed
    case cares about, so the rest can't silently pollute the base sum."""
    z = {c: 0.0 for c in CATEGORIES}
    z.update(overrides)
    return z


# --- base sum / punt exclusion ---------------------------------------------
#
# single player, every category given a distinct nonzero z so a punt subset
# provably removes only its own categories from the sum, not adjacent ones.
# base = 0.1+0.2+0.3+0.4+0.5+0.6+0.7+0.8+0.9 = 4.5
P1_Z = _z(
    fg_pct=0.1, ft_pct=0.2, tpm=0.3, pts=0.4, reb=0.5,
    ast=0.6, stl=0.7, blk=0.8, tov=0.9,
)
SOLO_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("UTIL", 1),))


def _solo_player(games: float = 82.0) -> DraftPoolPlayer:
    return DraftPoolPlayer(player_key="p1", position=None, projected_games=games, zscores=P1_Z)


def test_base_sums_all_nine_categories_when_no_punt():
    # solo player -> demand(UTIL) = 1*1 = 1, but pool has only 1 eligible
    # player, so the fallback branch fires and replacement = the player's
    # own base (deepest/only player defines the floor) -> vorp = 0 -> value
    # (pure vorp*games_factor, D4) = 0 too, exercising the whole pipeline on
    # the simplest case; base is still the full punt-aware 9-cat sum
    values = compute_draft_values([_solo_player()], SOLO_CONFIG)
    v = values["p1"]
    assert v.base == pytest.approx(4.5, abs=TOL)
    assert v.replacement == pytest.approx(4.5, abs=TOL)
    assert v.vorp == pytest.approx(0.0, abs=TOL)
    assert v.value == pytest.approx(0.0, abs=TOL)
    assert v.best_class == "UTIL"


def test_punt_excludes_category_from_base_sum_for_all_players():
    # punting reb (0.5) and tov (0.9) removes exactly those two: 4.5-0.5-0.9=3.1
    values = compute_draft_values([_solo_player()], SOLO_CONFIG, punt=frozenset({"reb", "tov"}))
    assert values["p1"].base == pytest.approx(3.1, abs=TOL)


def test_invalid_punt_category_raises_value_error():
    # match= pins the offending category name in the message, not just "some ValueError"
    with pytest.raises(ValueError, match="not_a_real_cat"):
        compute_draft_values([_solo_player()], SOLO_CONFIG, punt=frozenset({"not_a_real_cat"}))


def test_invalid_punt_category_raises_even_with_empty_player_list():
    # config/punt validation is a precondition check, independent of pool
    # state -- it must fire before the "empty pool -> {}" short-circuit
    with pytest.raises(ValueError, match="not_a_real_cat"):
        compute_draft_values([], SOLO_CONFIG, punt=frozenset({"not_a_real_cat"}))


def test_empty_player_list_returns_empty_dict():
    assert compute_draft_values([], SOLO_CONFIG) == {}


def test_default_roster_slots_matches_standard_yahoo_layout():
    assert DEFAULT_ROSTER_SLOTS == (
        ("PG", 1), ("SG", 1), ("G", 1), ("SF", 1), ("PF", 1), ("F", 1),
        ("C", 2), ("UTIL", 3), ("BN", 3), ("IL", 2),
    )


# --- LeagueConfig validation (I3) --------------------------------------------
#
# with num_teams < 1, or roster_slots that recognize zero starter slots
# (empty, or only BN/IL/typo'd names), every demand computes to 0 -> the
# "primary branch" index (min(demand, len-1)) becomes 0 -> replacement
# silently anchors to each class's BEST player instead of a real replacement
# level, inverting cross-class ordering rather than failing loudly. Both must
# raise instead.
def test_num_teams_below_one_raises_value_error():
    bad_config = LeagueConfig(num_teams=0, roster_slots=DEFAULT_ROSTER_SLOTS)
    with pytest.raises(ValueError, match="num_teams"):
        compute_draft_values([_solo_player()], bad_config)


def test_negative_num_teams_raises_value_error():
    bad_config = LeagueConfig(num_teams=-3, roster_slots=DEFAULT_ROSTER_SLOTS)
    with pytest.raises(ValueError, match="num_teams"):
        compute_draft_values([_solo_player()], bad_config)


def test_roster_slots_with_no_recognized_slots_raises_value_error():
    # BN/IL are real Yahoo slots but never count toward starter demand --
    # a roster_slots made only of those (or an empty tuple) recognizes zero
    # starter slots and must raise, not silently zero every demand
    bad_config = LeagueConfig(num_teams=12, roster_slots=(("BN", 3), ("IL", 2)))
    with pytest.raises(ValueError, match="roster_slots"):
        compute_draft_values([_solo_player()], bad_config)


def test_empty_roster_slots_raises_value_error():
    bad_config = LeagueConfig(num_teams=12, roster_slots=())
    with pytest.raises(ValueError, match="roster_slots"):
        compute_draft_values([_solo_player()], bad_config)


# --- demand rounds up (ceil), not down or to nearest ------------------------
#
# num_teams=5, roster_slots PG:1 + composite G:1, no UTIL:
#   demand(PG) = 5*(1 + 1/2 + 0/5) = 5*1.5 = 7.5 -> ceil = 8 (not 7)
# 12 PG-only players with base 12.0 .. 1.0 (descending by 1) so index 7
# (a wrong floor/round) and index 8 (correct ceil) land on different,
# distinguishable players: index7 -> base 5.0, index8 -> base 4.0.
CEIL_CONFIG = LeagueConfig(num_teams=5, roster_slots=(("PG", 1), ("G", 1)))


def test_demand_rounds_up_not_down_or_nearest():
    players = [
        DraftPoolPlayer(
            player_key=f"g{i}", position="PG", projected_games=82.0, zscores=_z(pts=float(i))
        )
        for i in range(12, 0, -1)  # bases 12.0 .. 1.0, descending
    ]
    values = compute_draft_values(players, CEIL_CONFIG)
    top = values["g12"]  # base 12.0, best_class must be PG (only eligibility)
    assert top.best_class == "PG"
    assert top.replacement == pytest.approx(4.0, abs=TOL)  # index 8 (ceil), not 5.0 (index 7)
    assert top.vorp == pytest.approx(8.0, abs=TOL)


# --- table-driven: composite map, C-has-no-composite, UTIL/5, and ceil, ----
# --- all pinned together on the PRIMARY replacement branch (index=demand) --
#
# num_teams=2, roster_slots PG:1, SG:1, G:1, SF:1, PF:1, F:2, C:2, UTIL:3
# (G count=1 and F count=2 are DELIBERATELY unequal, so PG/SG's composite
# ("G") and SF/PF's composite ("F") produce different demand -- a SF-uses-
# "G"-instead-of-"F" bug would make demand(SF) collapse to demand(PG)'s
# value instead of its own).
#
# demand(PG) = demand(SG) = ceil(2*(1 + 1/2 + 3/5)) = ceil(2*2.1) = ceil(4.2) = 5
# demand(SF) = demand(PF) = ceil(2*(1 + 2/2 + 3/5)) = ceil(2*2.6) = ceil(5.2) = 6
# demand(C)  =              ceil(2*(2 + 0   + 3/5)) = ceil(2*2.6) = ceil(5.2) = 6
#   (C's composite_count is 0 -- it has no composite slot at all)
#
# Each position gets its own single-eligibility pool (e.g. position="PG" is
# only PG-eligible, never SG/G-cross-contaminating), built strictly
# descending by 1 so sort order == construction order == base value, and
# each pool is deeper than demand+1 so the PRIMARY branch fires
# (index = demand exactly), not the len-1 fallback:
#
#   class | demand | pool bases (desc)      | pool size | index | replacement
#   ------+--------+-------------------------+-----------+-------+------------
#   PG    |   5    | 107, 106, ..., 100      |     8     |   5   |    102
#   SG    |   5    | 207, 206, ..., 200      |     8     |   5   |    202
#   SF    |   6    | 306, 305, ..., 298      |     9     |   6   |    300
#   PF    |   6    | 406, 405, ..., 398      |     9     |   6   |    400
#   C     |   6    | 506, 505, ..., 498      |     9     |   6   |    500
#
# (each index picked with margin above demand+1's boundary -- e.g. PG pool
# size 8 > demand+1=6 -- so there's no ambiguity between "index=demand" and
# "index=len-1" coinciding by coincidence)
TABLE_CONFIG = LeagueConfig(
    num_teams=2,
    roster_slots=(("PG", 1), ("SG", 1), ("G", 1), ("SF", 1), ("PF", 1), ("F", 2), ("C", 2), ("UTIL", 3)),
)


def _pos_pool(position: str, start_base: float, count: int) -> list[DraftPoolPlayer]:
    """count players, single-eligibility at `position`, bases descending by 1
    from start_base -- sort order matches construction order by design."""
    return [
        DraftPoolPlayer(
            player_key=f"{position.lower()}_{i}", position=position,
            projected_games=82.0, zscores=_z(pts=start_base - i),
        )
        for i in range(count)
    ]


def test_composite_map_c_no_composite_util_spread_and_ceil_all_pinned_together():
    pool = (
        _pos_pool("PG", 107.0, 8)
        + _pos_pool("SG", 207.0, 8)
        + _pos_pool("SF", 306.0, 9)
        + _pos_pool("PF", 406.0, 9)
        + _pos_pool("C", 506.0, 9)
    )
    values = compute_draft_values(pool, TABLE_CONFIG)

    expected_replacement = {"pg": 102.0, "sg": 202.0, "sf": 300.0, "pf": 400.0, "c": 500.0}
    for position, replacement in expected_replacement.items():
        top = values[f"{position}_0"]  # the best player in that position's pool
        assert top.best_class == position.upper(), position
        assert top.replacement == pytest.approx(replacement, abs=TOL), position

    # every class's replacement must be distinct -- catches both a SF/PF-uses-
    # "G" composite bug (would collapse SF/PF's replacement toward PG/SG's)
    # and a deleted-UTIL/5 bug (would shift every replacement uniformly)
    assert len(set(expected_replacement.values())) == 5


# --- replacement fallback when pool is shallower than demand ----------------
#
# num_teams=1, roster_slots PG:3, no composite/UTIL -> demand(PG) = 1*3 = 3.
# Only 2 PG-eligible players exist, so demand+1(=4) > pool size(2): fall back
# to the base of the LAST (worst) eligible player rather than indexing OOB.
FALLBACK_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("PG", 3),))


def test_replacement_falls_back_to_worst_eligible_when_pool_smaller_than_demand():
    strong = DraftPoolPlayer(player_key="strong", position="PG", projected_games=82.0, zscores=_z(pts=5.0))
    weak = DraftPoolPlayer(player_key="weak", position="PG", projected_games=82.0, zscores=_z(pts=2.0))
    values = compute_draft_values([strong, weak], FALLBACK_CONFIG)
    assert values["strong"].replacement == pytest.approx(2.0, abs=TOL)
    assert values["strong"].vorp == pytest.approx(3.0, abs=TOL)
    assert values["weak"].replacement == pytest.approx(2.0, abs=TOL)
    assert values["weak"].vorp == pytest.approx(0.0, abs=TOL)


# --- positional scarcity: a thin position outranks a deeper one in VORP -----
#
# 12-team default Yahoo layout. demand(C) = ceil(12*(2+0+3/5)) = ceil(31.2) = 32;
# demand(PG) = ceil(12*(1+1/2+3/5)) = ceil(25.2) = 26. Both demands vastly
# exceed this 2-player-per-position pool, so both replacements use the
# fallback (worst-eligible) branch -- this is a legitimate, spec-defined path
# (not a hack): a real endpoint's pool can easily be shallower than demand at
# a given moment (early draft, filtered pool, etc).
#
# star_center: reb 3.0 + blk 2.0 - ft_pct 1.0 = base 4.0
# scrub_center: reb -3.0 = base -3.0            -> replacement(C) = -3.0
# star_guard: ast 2.5 + pts 2.0 + stl 0.7 = base 5.2
# scrub_guard: ast 0.3 + pts 0.2 = base 0.5      -> replacement(PG) = 0.5
#
# vorp(star_center) = 4.0 - (-3.0) = 7.0
# vorp(star_guard)  = 5.2 - 0.5    = 4.7
# -> star_center (lower base) beats star_guard (higher base) in VORP: the
#    center pool is thinner (its worst eligible player is far worse than the
#    guard pool's worst eligible player), so scarcity rewards the center more.
#
# D4: value = vorp * games_factor (no replacement term). Both players are at
# full projected games (82 -> games_factor=1), so value == vorp exactly here,
# and the scarcity-driven vorp flip is therefore also a value flip -- the
# final draft-order number itself now reflects positional scarcity directly,
# not just the display-only vorp/replacement fields.
DEFAULT_CONFIG = LeagueConfig(num_teams=12, roster_slots=DEFAULT_ROSTER_SLOTS)


def test_scarce_position_outranks_higher_base_player_in_value():
    star_center = DraftPoolPlayer(
        player_key="star_center", position="C", projected_games=82.0,
        zscores=_z(reb=3.0, blk=2.0, ft_pct=-1.0),
    )
    scrub_center = DraftPoolPlayer(
        player_key="scrub_center", position="C", projected_games=82.0, zscores=_z(reb=-3.0)
    )
    star_guard = DraftPoolPlayer(
        player_key="star_guard", position="PG", projected_games=82.0,
        zscores=_z(ast=2.5, pts=2.0, stl=0.7),
    )
    scrub_guard = DraftPoolPlayer(
        player_key="scrub_guard", position="PG", projected_games=82.0,
        zscores=_z(ast=0.3, pts=0.2),
    )
    values = compute_draft_values(
        [star_center, scrub_center, star_guard, scrub_guard], DEFAULT_CONFIG
    )

    assert values["star_center"].base == pytest.approx(4.0, abs=TOL)
    assert values["star_guard"].base == pytest.approx(5.2, abs=TOL)
    assert values["star_center"].base < values["star_guard"].base  # lower raw base ...

    assert values["star_center"].replacement == pytest.approx(-3.0, abs=TOL)
    assert values["star_guard"].replacement == pytest.approx(0.5, abs=TOL)
    assert values["star_center"].vorp == pytest.approx(7.0, abs=TOL)
    assert values["star_guard"].vorp == pytest.approx(4.7, abs=TOL)

    assert values["star_center"].best_class == "C"
    assert values["star_guard"].best_class == "PG"

    # the actual required flip: final draft value, not just vorp
    assert values["star_center"].value == pytest.approx(7.0, abs=TOL)
    assert values["star_guard"].value == pytest.approx(4.7, abs=TOL)
    assert values["star_center"].value > values["star_guard"].value  # scarce big outranks the guard


# --- punt recomputation flips a ranking -------------------------------------
#
# both players position C (same base class -> isolates the punt-driven base
# flip from any cross-position scarcity effect). num_teams=1, roster_slots
# C:1 -> demand(C) = 1*(1+0+0) = 1; pool of 2 -> primary branch, index 1
# (0-indexed) = the worse of the two.
#
# good_ft_big: ft_pct +2.0, pts +0.1 -> base = 2.1
# poor_ft_big: ft_pct -3.0, pts +2.0 -> base = -1.0
#   no punt: sorted desc [good(2.1), poor(-1.0)], index 1 -> replacement = -1.0
#     vorp(good) = 2.1-(-1.0) = 3.1 -> value (games_factor=1) = 3.1
#     vorp(poor) = -1.0-(-1.0) = 0.0 -> value = 0.0
#   no punt: good_ft_big (3.1) > poor_ft_big (0.0)
#
# punt={ft_pct}: good -> 2.1-2.0=0.1; poor -> -1.0-(-3.0)=2.0
#   sorted desc [poor(2.0), good(0.1)], index 1 -> replacement = 0.1
#     vorp(poor) = 2.0-0.1 = 1.9 -> value = 1.9
#     vorp(good) = 0.1-0.1 = 0.0 -> value = 0.0
#   punted: poor_ft_big (1.9) > good_ft_big (0.0)  -- ranking flips
PUNT_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("C", 1),))


def test_punt_recomputation_flips_ranking():
    good_ft_big = DraftPoolPlayer(
        player_key="good_ft_big", position="C", projected_games=82.0,
        zscores=_z(ft_pct=2.0, pts=0.1),
    )
    poor_ft_big = DraftPoolPlayer(
        player_key="poor_ft_big", position="C", projected_games=82.0,
        zscores=_z(ft_pct=-3.0, pts=2.0),
    )
    pool = [good_ft_big, poor_ft_big]

    no_punt = compute_draft_values(pool, PUNT_CONFIG)
    assert no_punt["good_ft_big"].value > no_punt["poor_ft_big"].value
    assert no_punt["good_ft_big"].value == pytest.approx(3.1, abs=TOL)
    assert no_punt["poor_ft_big"].value == pytest.approx(0.0, abs=TOL)

    punted = compute_draft_values(pool, PUNT_CONFIG, punt=frozenset({"ft_pct"}))
    assert punted["poor_ft_big"].value > punted["good_ft_big"].value
    assert punted["poor_ft_big"].value == pytest.approx(1.9, abs=TOL)
    assert punted["good_ft_big"].value == pytest.approx(0.0, abs=TOL)


# --- games risk shrinks value toward 0 (D4: pure vorp*games_factor), not ---
# --- toward replacement -----------------------------------------------------
#
# 3 UTIL-only (position None) players, roster_slots UTIL:2, num_teams=1 ->
# demand(UTIL) = 1*2 = 2; pool of 3 -> primary branch, index 2 = the worst.
# durable/risky share an identical base (5.0); bench sets a deliberately
# NONZERO replacement floor (1.0) so this test can prove value shrinks
# toward 0, not toward that replacement level.
# sorted desc (stable, ties keep input order): [durable, risky, bench]
# -> replacement(UTIL) = bench's base = 1.0
#
# durable: vorp=5.0-1.0=4.0, games=82   -> gf=1.0  -> value = 4.0*1.0  = 4.0
# risky:   vorp=5.0-1.0=4.0, games=61.5 -> gf=0.75 -> value = 4.0*0.75 = 3.0
# risky's value (3.0) is below durable's (4.0), still positive, and is NOT
# equal to the replacement level (1.0) -- confirms the shrink target is 0,
# not replacement.
GAMES_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("UTIL", 2),))


def test_games_risk_shrinks_value_toward_zero_not_replacement():
    durable = DraftPoolPlayer(player_key="durable", position=None, projected_games=82.0, zscores=_z(pts=5.0))
    risky = DraftPoolPlayer(player_key="risky", position=None, projected_games=61.5, zscores=_z(pts=5.0))
    bench = DraftPoolPlayer(player_key="bench", position=None, projected_games=82.0, zscores=_z(pts=1.0))

    values = compute_draft_values([durable, risky, bench], GAMES_CONFIG)
    assert values["risky"].replacement == pytest.approx(1.0, abs=TOL)
    assert values["durable"].value == pytest.approx(4.0, abs=TOL)
    assert values["risky"].value == pytest.approx(3.0, abs=TOL)
    assert values["risky"].value < values["durable"].value  # identical player, fewer games -> ranks lower
    assert values["risky"].value > 0.0  # still above 0, since games_factor > 0 and vorp > 0
    assert values["risky"].value != pytest.approx(values["risky"].replacement, abs=TOL)  # not shrinking toward replacement


def test_games_factor_floors_at_zero_for_zero_or_negative_projected_games():
    # zero and negative projected_games must both floor games_factor at 0.0;
    # for a POSITIVE-vorp player that collapses value to exactly 0.0 (not to
    # replacement, and not negative gf/value) -- D4: value = vorp*games_factor
    zero_games = DraftPoolPlayer(player_key="zero_games", position=None, projected_games=0.0, zscores=_z(pts=5.0))
    negative_games = DraftPoolPlayer(
        player_key="negative_games", position=None, projected_games=-10.0, zscores=_z(pts=5.0)
    )
    bench = DraftPoolPlayer(player_key="bench", position=None, projected_games=82.0, zscores=_z(pts=1.0))

    values = compute_draft_values([zero_games, negative_games, bench], GAMES_CONFIG)
    assert values["zero_games"].vorp > 0.0  # positive-vorp player, to isolate the floor's effect
    assert values["zero_games"].value == pytest.approx(0.0, abs=TOL)
    assert values["negative_games"].value == pytest.approx(0.0, abs=TOL)
    assert values["zero_games"].value == pytest.approx(values["negative_games"].value, abs=TOL)


# --- below-replacement players carry negative value (D4: pure vorp units) --
#
# num_teams=1, roster_slots PG:1 (no composite/UTIL) -> demand(PG) = 1*1 = 1.
# 3 PG-eligible players, pool deeper than demand -> primary branch:
# sorted desc [high(5.0), mid(2.0), low(-3.0)], index 1 -> replacement = 2.0
# vorp(low) = -3.0 - 2.0 = -5.0; at full games (gf=1) value = -5.0*1 = -5.0
NEGATIVE_VALUE_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("PG", 1),))


def test_below_replacement_player_has_negative_value_at_full_health():
    high = DraftPoolPlayer(player_key="high", position="PG", projected_games=82.0, zscores=_z(pts=5.0))
    mid = DraftPoolPlayer(player_key="mid", position="PG", projected_games=82.0, zscores=_z(pts=2.0))
    low = DraftPoolPlayer(player_key="low", position="PG", projected_games=82.0, zscores=_z(pts=-3.0))

    values = compute_draft_values([high, mid, low], NEGATIVE_VALUE_CONFIG)
    assert values["low"].replacement == pytest.approx(2.0, abs=TOL)
    assert values["low"].vorp == pytest.approx(-5.0, abs=TOL)
    assert values["low"].value == pytest.approx(-5.0, abs=TOL)
    assert values["low"].value < 0.0
    assert values["high"].value == pytest.approx(3.0, abs=TOL)  # contrast: positive vorp -> positive value


# --- multi-position eligibility picks the more favorable class -------------
#
# num_teams=1, roster_slots PG:1 + SF:1 (no composite/UTIL) ->
# demand(PG) = demand(SF) = 1*(1+0+0) = 1; pool of 2 per position -> primary
# branch, index 1 = the other player in each pair.
#
# m (position "PG-SF"): base 5.0, eligible at both PG and SF
# g_low (PG only): base 1.0 -> replacement(PG) = 1.0 -> vorp(m via PG) = 4.0
# f_low (SF only): base 3.0 -> replacement(SF) = 3.0 -> vorp(m via SF) = 2.0
# -> m must pick PG (4.0 > 2.0), the more favorable class
MULTI_POS_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("PG", 1), ("SF", 1)))


def test_multi_position_eligibility_picks_more_favorable_class():
    m = DraftPoolPlayer(player_key="m", position="PG-SF", projected_games=82.0, zscores=_z(pts=5.0))
    g_low = DraftPoolPlayer(player_key="g_low", position="PG", projected_games=82.0, zscores=_z(pts=1.0))
    f_low = DraftPoolPlayer(player_key="f_low", position="SF", projected_games=82.0, zscores=_z(pts=3.0))

    values = compute_draft_values([m, g_low, f_low], MULTI_POS_CONFIG)
    assert values["m"].best_class == "PG"
    assert values["m"].replacement == pytest.approx(1.0, abs=TOL)
    assert values["m"].vorp == pytest.approx(4.0, abs=TOL)


# --- UTIL-only fallback path -------------------------------------------------
#
# num_teams=1, roster_slots UTIL:2 (no direct positions at all) ->
# demand(UTIL) = 1*2 = 2. u (position None) has no base-position eligibility,
# so it must fall back to the pseudo "UTIL" class, whose eligible pool is
# ALL players regardless of their own position (other1, other2 included even
# though they're PG/SG, not UTIL-only themselves).
# sorted desc: [other1(6.0), u(4.0), other2(1.0)] -> index 2 -> replacement = 1.0
# vorp(u) = 4.0 - 1.0 = 3.0
UTIL_FALLBACK_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("UTIL", 2),))


def test_util_only_fallback_uses_pseudo_class_over_whole_pool():
    u = DraftPoolPlayer(player_key="u", position=None, projected_games=82.0, zscores=_z(pts=4.0))
    other1 = DraftPoolPlayer(player_key="other1", position="PG", projected_games=82.0, zscores=_z(pts=6.0))
    other2 = DraftPoolPlayer(player_key="other2", position="SG", projected_games=82.0, zscores=_z(pts=1.0))

    values = compute_draft_values([u, other1, other2], UTIL_FALLBACK_CONFIG)
    assert values["u"].best_class == "UTIL"
    assert values["u"].replacement == pytest.approx(1.0, abs=TOL)
    assert values["u"].vorp == pytest.approx(3.0, abs=TOL)


# --- strict tie-break: exact-vorp ties resolve to canonical order ----------
#
# num_teams=1, roster_slots SG:1 + PF:1 (no composite/UTIL) ->
# demand(SG) = demand(PF) = 1*(1+0+0) = 1; pool of 2 per position -> primary
# branch, index 1 = the other player in each pair.
#
# m2 (position "PF-SG" -- deliberately PF listed BEFORE SG in the label, to
#   prove the tie-break follows BASE_POSITIONS canonical order (PG,SG,SF,
#   PF,C), not the label's own token order and not frozenset iteration
#   order): base 6.0, eligible at both SG and PF
# sg_low (SG only): base 2.0 -> replacement(SG) = 2.0 -> vorp(m2 via SG) = 4.0
# pf_low (PF only): base 2.0 -> replacement(PF) = 2.0 -> vorp(m2 via PF) = 4.0
# -> exact tie (4.0 == 4.0); canonical order requires SG (earlier than PF)
TIE_BREAK_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("SG", 1), ("PF", 1)))


def test_exact_vorp_tie_breaks_to_earlier_canonical_class():
    m2 = DraftPoolPlayer(player_key="m2", position="PF-SG", projected_games=82.0, zscores=_z(pts=6.0))
    sg_low = DraftPoolPlayer(player_key="sg_low", position="SG", projected_games=82.0, zscores=_z(pts=2.0))
    pf_low = DraftPoolPlayer(player_key="pf_low", position="PF", projected_games=82.0, zscores=_z(pts=2.0))

    values = compute_draft_values([m2, sg_low, pf_low], TIE_BREAK_CONFIG)
    assert values["m2"].replacement == pytest.approx(2.0, abs=TOL)
    assert values["m2"].vorp == pytest.approx(4.0, abs=TOL)
    assert values["m2"].best_class == "SG"  # canonical PG,SG,SF,PF,C order wins the tie, not label order


def test_compute_draft_values_is_deterministic_across_repeated_calls():
    # NOTE on what this actually guards: a single pytest process has one
    # fixed hash seed for its whole lifetime, so two calls in the SAME
    # process can never observe hash-seed-driven nondeterminism -- this test
    # cannot catch that class of bug (see the subprocess test below for the
    # real cross-process guard). What it DOES guard: within-run stability and
    # that compute_draft_values doesn't mutate its inputs or carry hidden
    # state between calls (frozen dataclasses compare by value, so dict
    # equality checks every field for every player).
    m2 = DraftPoolPlayer(player_key="m2", position="PF-SG", projected_games=82.0, zscores=_z(pts=6.0))
    sg_low = DraftPoolPlayer(player_key="sg_low", position="SG", projected_games=82.0, zscores=_z(pts=2.0))
    pf_low = DraftPoolPlayer(player_key="pf_low", position="PF", projected_games=82.0, zscores=_z(pts=2.0))
    pool = [m2, sg_low, pf_low]

    first = compute_draft_values(pool, TIE_BREAK_CONFIG)
    second = compute_draft_values(pool, TIE_BREAK_CONFIG)
    assert first == second
    assert first["m2"].best_class == second["m2"].best_class == "SG"


# --- real cross-process hash-randomization guard -----------------------------
#
# each `python -c ...` invocation below is a brand-new process with its own
# PYTHONHASHSEED, so (unlike the in-process test above) this actually
# exercises whatever hash seed CPython picks for that run. Runs the same
# tie-break scenario as test_exact_vorp_tie_breaks_to_earlier_canonical_class
# at two explicit, different seeds and asserts identical best_class output.
_TIE_BREAK_SCRIPT = """
from ninecat.engine.draft import DraftPoolPlayer, LeagueConfig, compute_draft_values
from ninecat.engine.zscores import CATEGORIES

def z(pts):
    d = {c: 0.0 for c in CATEGORIES}
    d["pts"] = pts
    return d

m2 = DraftPoolPlayer(player_key="m2", position="PF-SG", projected_games=82.0, zscores=z(6.0))
sg_low = DraftPoolPlayer(player_key="sg_low", position="SG", projected_games=82.0, zscores=z(2.0))
pf_low = DraftPoolPlayer(player_key="pf_low", position="PF", projected_games=82.0, zscores=z(2.0))
config = LeagueConfig(num_teams=1, roster_slots=(("SG", 1), ("PF", 1)))
values = compute_draft_values([m2, sg_low, pf_low], config)
print(values["m2"].best_class)
"""

_BACKEND_SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")


def test_best_class_tie_break_is_identical_across_hash_seeds():
    outputs = []
    for seed in ("0", "42"):
        env = {**os.environ, "PYTHONPATH": _BACKEND_SRC_DIR, "PYTHONHASHSEED": seed}
        result = subprocess.run(
            [sys.executable, "-c", _TIE_BREAK_SCRIPT],
            env=env, capture_output=True, text=True, check=True, timeout=30,
        )
        outputs.append(result.stdout.strip())
    assert outputs == ["SG", "SG"]
