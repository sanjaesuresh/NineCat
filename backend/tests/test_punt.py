from dataclasses import FrozenInstanceError

import pytest

from ninecat.engine.draft import DraftPoolPlayer, LeagueConfig, compute_draft_values
from ninecat.engine.punt import PuntSuggestion, suggest_punt_builds
from ninecat.engine.zscores import CATEGORIES

TOL = 1e-3

# solo-UTIL config used throughout: no positional scarcity noise, so pool_delta
# math is driven purely by base z-sum, not replacement-level games
SOLO_CONFIG = LeagueConfig(num_teams=1, roster_slots=(("UTIL", 1),))


def _z(**overrides: float) -> dict[str, float]:
    """All nine categories default to 0.0; pass only the ones a hand-computed
    case cares about, so the rest can't silently pollute the roster mean."""
    z = {c: 0.0 for c in CATEGORIES}
    z.update(overrides)
    return z


def _player(key: str, **overrides: float) -> DraftPoolPlayer:
    return DraftPoolPlayer(player_key=key, position=None, projected_games=82.0, zscores=_z(**overrides))


# --- empty / no-basis inputs -------------------------------------------------


def test_empty_roster_returns_empty_list():
    # no roster -> no basis to advise, regardless of how juicy the pool is
    pool = [_player("p1", ft_pct=-5.0)]
    assert suggest_punt_builds([], pool, SOLO_CONFIG) == []


def test_all_strong_roster_returns_empty_list():
    # every category >= 0 -> nothing qualifies as a punt candidate
    roster = [_player("me", **{c: 0.5 for c in CATEGORIES})]
    assert suggest_punt_builds(roster, [], SOLO_CONFIG) == []


# --- plausibility: poor-FT bigs ---------------------------------------------


def test_poor_ft_bigs_rank_ft_pct_punt_first():
    # a "big man" archetype: strong reb/blk/fg%, weak ft%/3s/ast/stl, and
    # ft_pct is by far the most negative -> its single-category improvement
    # dominates every other candidate even after the pair-size penalty
    roster = [
        _player(
            "big",
            ft_pct=-1.5, ast=-0.5, tpm=-0.6, stl=-0.1,
            fg_pct=0.4, reb=0.9, blk=0.8, pts=0.3,
        )
    ]
    suggestions = suggest_punt_builds(roster, [], SOLO_CONFIG, limit=20)
    assert suggestions
    assert "ft_pct" in suggestions[0].punt


def test_strong_categories_never_appear_in_any_suggestion():
    # same weak-FT-bigs roster: fg_pct/reb/blk/pts are all >= 0 (strengths)
    # and must never show up in a punted set, across every returned candidate
    roster = [
        _player(
            "big",
            ft_pct=-1.5, ast=-0.5, tpm=-0.6, stl=-0.1,
            fg_pct=0.4, reb=0.9, blk=0.8, pts=0.3,
        )
    ]
    suggestions = suggest_punt_builds(roster, [], SOLO_CONFIG, limit=20)
    strong_cats = {"fg_pct", "reb", "blk", "pts"}
    for s in suggestions:
        assert not (s.punt & strong_cats)


def test_limit_is_respected():
    # 4 qualifying cats -> C(4,1)+C(4,2) = 4+6 = 10 candidates; limit caps it
    roster = [
        _player(
            "big",
            ft_pct=-1.5, ast=-0.5, tpm=-0.6, stl=-0.1,
            fg_pct=0.4, reb=0.9, blk=0.8, pts=0.3,
        )
    ]
    suggestions = suggest_punt_builds(roster, [], SOLO_CONFIG, limit=3)
    assert len(suggestions) == 3


# --- pair-vs-single score penalty, pinned numerically -----------------------


def test_pair_vs_single_penalty_is_pinned():
    # single player -> roster mean == the player's own z (n=1)
    # z: ft_pct=-1.0, blk=-0.5, other 7 cats = 0.0
    # overall_mean = (-1.0 - 0.5) / 9 = -1.5/9 = -0.166667
    #
    # punt={ft_pct}: remaining sum = -0.5 (blk) + 0*7 = -0.5, mean = -0.5/8 = -0.0625
    #   improvement = -0.0625 - (-0.166667) = 0.104167
    #   score = 0.104167 (pool empty -> pool_delta=0, no size penalty)
    #
    # punt={blk}: remaining sum = -1.0 (ft_pct) + 0*7 = -1.0, mean = -1.0/8 = -0.125
    #   improvement = -0.125 - (-0.166667) = 0.041667
    #   score = 0.041667
    #
    # punt={ft_pct,blk}: remaining sum = 0 (7 zeros), mean = 0.0
    #   improvement = 0.0 - (-0.166667) = 0.166667  <- biggest raw improvement
    #   score = 0.166667 - 0.15*(2-1) = 0.016667     <- but penalty drops it
    #   BELOW both singles, proving the size penalty actually bites
    roster = [_player("me", ft_pct=-1.0, blk=-0.5)]
    suggestions = suggest_punt_builds(roster, [], SOLO_CONFIG, limit=3)

    by_punt = {s.punt: s for s in suggestions}
    single_ft = by_punt[frozenset({"ft_pct"})]
    single_blk = by_punt[frozenset({"blk"})]
    pair = by_punt[frozenset({"ft_pct", "blk"})]

    assert single_ft.score == pytest.approx(0.104167, abs=TOL)
    assert single_blk.score == pytest.approx(0.041667, abs=TOL)
    assert pair.score == pytest.approx(0.016667, abs=TOL)

    # the pair's raw improvement is bigger than either single's...
    assert pair.improvement > single_ft.improvement
    assert pair.improvement > single_blk.improvement
    # ...but the size penalty pushes its final score below both singles
    assert pair.score < single_ft.score
    assert pair.score < single_blk.score

    # and the ranking (score desc) reflects it
    assert [s.punt for s in suggestions] == [
        frozenset({"ft_pct"}),
        frozenset({"blk"}),
        frozenset({"ft_pct", "blk"}),
    ]


# --- deterministic tie-break --------------------------------------------------


def test_tie_break_is_deterministic_and_pinned():
    # fg_pct and ft_pct given identical means (-1.0) -> their single-category
    # candidates tie exactly on score (pool empty, same arithmetic either
    # way). Score is the PRIMARY sort key throughout: the pair sorts last
    # here because its own score (0.222222 - 0.15 = 0.072222) is lower than
    # either single's (0.097222) -- the pair-size tiebreak only ever matters
    # between candidates that are ALREADY tied on score, which is exactly
    # the fg_pct-vs-ft_pct case this test pins.
    # CATEGORIES = (fg_pct, ft_pct, tpm, pts, reb, ast, stl, blk, tov)
    # -> fg_pct (index 0) sorts before ft_pct (index 1) via canonical order.
    roster = [_player("me", fg_pct=-1.0, ft_pct=-1.0)]
    suggestions = suggest_punt_builds(roster, [], SOLO_CONFIG, limit=3)

    assert [s.punt for s in suggestions] == [
        frozenset({"fg_pct"}),
        frozenset({"ft_pct"}),
        frozenset({"fg_pct", "ft_pct"}),
    ]
    # exact tie: both singles must have bit-identical scores
    assert suggestions[0].score == suggestions[1].score
    # empty pool -> pool_delta is always exactly 0.0, never approximate
    assert all(s.pool_delta == 0.0 for s in suggestions)


# --- pool_delta computed under the punt --------------------------------------


def test_pool_value_rises_for_poor_ft_player_when_ft_pct_punted():
    # direct engine-level check of the premise pool_delta relies on: removing
    # ft_pct from the base sum should raise a poor-FT player's draft value.
    # A: ft_pct=-2.0, other 8 cats=1.0 -> base(no punt)=8*1.0-2.0=6.0; base(punt ft_pct)=8*1.0=8.0
    # B: all 9 cats=0.5 -> base(no punt)=4.5; base(punt ft_pct)=4.0
    # C: all 9 cats=-0.5 -> base(no punt)=-4.5; base(punt ft_pct)=-4.0
    # demand(UTIL) = ceil(1 team * 1 slot) = 1 -> replacement = 2nd-best base (index 1)
    #
    # no punt: bases sorted [6.0, 4.5, -4.5] -> replacement=4.5
    #   vorp: A=1.5, B=0.0, C=-9.0
    # punt ft_pct: bases sorted [8.0, 4.0, -4.0] -> replacement=4.0
    #   vorp: A=4.0, B=0.0, C=-8.0
    a = _player("A", ft_pct=-2.0, fg_pct=1.0, tpm=1.0, pts=1.0, reb=1.0, ast=1.0, stl=1.0, blk=1.0, tov=1.0)
    b = _player("B", **{c: 0.5 for c in CATEGORIES})
    c = _player("C", **{c: -0.5 for c in CATEGORIES})
    pool = [a, b, c]

    no_punt = compute_draft_values(pool, SOLO_CONFIG)
    punt_ft = compute_draft_values(pool, SOLO_CONFIG, punt=frozenset({"ft_pct"}))

    assert no_punt["A"].value == pytest.approx(1.5, abs=TOL)
    assert punt_ft["A"].value == pytest.approx(4.0, abs=TOL)
    assert punt_ft["A"].value > no_punt["A"].value


def test_suggest_punt_builds_pool_delta_pinned():
    # my_players = [A] from the case above -> roster mean == A's own z, so
    # ft_pct (-2.0) is the only qualifying category (all other 8 are +1.0).
    # overall_mean = (-2.0 + 8*1.0)/9 = 6.0/9 = 0.666667
    # improvement({ft_pct}) = mean(remaining 8 cats, all 1.0) - overall_mean
    #   = 1.0 - 0.666667 = 0.333333
    #
    # pool = [A, B, C] (values from the direct test above):
    #   no-punt (9 cats): top-3 mean = -7.5/3 = -2.5, normalized /9 = -0.277778
    #   punt-ft (8 cats): top-3 mean = -4.0/3 = -1.333333, normalized /8 = -0.166667
    # per-category normalization (each side divided by ITS OWN remaining
    # category count) puts both sides on the same value-per-category scale --
    # see the pool_delta comment in punt.py for why the un-normalized
    # difference would otherwise be a scale artifact, not a real signal
    # pool_delta = -0.166667 - (-0.277778) = 0.111111
    #
    # score = improvement + 0.5*pool_delta - 0.15*(1-1)
    #       = 0.333333 + 0.5*0.111111 = 0.333333 + 0.055556 = 0.388889
    a = _player("A", ft_pct=-2.0, fg_pct=1.0, tpm=1.0, pts=1.0, reb=1.0, ast=1.0, stl=1.0, blk=1.0, tov=1.0)
    b = _player("B", **{c: 0.5 for c in CATEGORIES})
    c = _player("C", **{c: -0.5 for c in CATEGORIES})
    pool = [a, b, c]

    suggestions = suggest_punt_builds([a], pool, SOLO_CONFIG, limit=3)

    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.punt == frozenset({"ft_pct"})
    assert s.punt_ordered == ("ft_pct",)
    assert s.improvement == pytest.approx(0.333333, abs=TOL)
    assert s.pool_delta == pytest.approx(0.111111, abs=TOL)
    assert s.score == pytest.approx(0.388889, abs=TOL)
    # weakest/weakest_mean are the raw contract fields (I2): a caller composes
    # its own label from these instead of parsing the English rationale
    assert s.weakest == "ft_pct"
    assert s.weakest_mean == pytest.approx(-2.0, abs=TOL)
    assert s.rationale == "Your roster is already weak in ft_pct (mean z -2.00); punting it frees value elsewhere."


# --- rationale sentence -------------------------------------------------------


def test_rationale_names_weakest_punted_category_for_a_pair():
    # fg_pct and ft_pct tie at mean z -1.00 -> canonical-order tiebreak makes
    # fg_pct the "weakest" named in the pair's rationale, per CATEGORIES order
    roster = [_player("me", fg_pct=-1.0, ft_pct=-1.0)]
    suggestions = suggest_punt_builds(roster, [], SOLO_CONFIG, limit=3)
    pair = next(s for s in suggestions if s.punt == frozenset({"fg_pct", "ft_pct"}))
    assert pair.weakest == "fg_pct"
    assert pair.weakest_mean == pytest.approx(-1.0, abs=TOL)
    assert pair.rationale == (
        "Your roster is already weak in fg_pct (mean z -1.00); "
        "punting it and ft_pct frees value elsewhere."
    )


# --- punt_ordered: deterministic JSON-safe boundary shape --------------------


def test_punt_ordered_is_canonical_for_a_pair_regardless_of_construction_order():
    # fg_pct/ft_pct pair, same tie-break scenario as above. `punt` (a
    # frozenset) has no meaningful "construction order" of its own -- the
    # point is that punt_ordered, derived from it, is always the canonical
    # CATEGORIES-index order, however the matching frozenset is spelled here.
    roster = [_player("me", fg_pct=-1.0, ft_pct=-1.0)]
    suggestions = suggest_punt_builds(roster, [], SOLO_CONFIG, limit=3)

    pair_reverse_literal = frozenset({"ft_pct", "fg_pct"})  # ft_pct written first
    pair = next(s for s in suggestions if s.punt == pair_reverse_literal)

    assert pair.punt_ordered == ("fg_pct", "ft_pct")
    # independent check: canonical order is always CATEGORIES-index order,
    # never the frozenset's own (hash-dependent, nondeterministic) iteration
    assert pair.punt_ordered == tuple(sorted(pair.punt, key=CATEGORIES.index))

    singles = [s for s in suggestions if len(s.punt) == 1]
    assert {s.punt_ordered for s in singles} == {("fg_pct",), ("ft_pct",)}


# --- realistic-pool plausibility (I1/normalization fix) ---------------------
#
# Modeled loosely on the dev-seed archetype: elite sub-60%-FT centers (strong
# reb/blk, weak ast/tpm) alongside a spread of balanced guards/wings (solid
# ft_pct, mild everywhere else). Shared across the R1/R2/R3 cases below so a
# single realistic pool backs all three roster variants the controller asked
# to be checked (R1: 2 bigs, R2: 3 bigs, R3: 2 bigs + 1 balanced guard).
_REALISTIC_BIGS = [
    _player(
        "big1", ft_pct=-2.2, reb=1.9, blk=1.6, fg_pct=0.7,
        ast=-0.6, tpm=-1.1, pts=0.4, stl=-0.3, tov=-0.2,
    ),
    _player(
        "big2", ft_pct=-1.9, reb=1.6, blk=1.3, fg_pct=0.5,
        ast=-0.5, tpm=-1.0, pts=0.2, stl=-0.2, tov=-0.1,
    ),
    _player(
        "big3", ft_pct=-1.6, reb=1.4, blk=1.1, fg_pct=0.4,
        ast=-0.4, tpm=-0.9, pts=0.1, stl=-0.1, tov=0.0,
    ),
]
_REALISTIC_BALANCED = [
    _player("bal1", ft_pct=0.8, tpm=0.6, ast=0.5, stl=0.3, pts=0.4, fg_pct=0.1, reb=-0.3, blk=-0.4, tov=0.1),
    _player("bal2", ft_pct=0.6, tpm=0.5, ast=0.6, stl=0.2, pts=0.3, fg_pct=0.0, reb=-0.2, blk=-0.3, tov=0.2),
    _player("bal3", ft_pct=0.5, tpm=0.3, ast=0.3, stl=0.4, pts=0.2, fg_pct=0.1, reb=-0.1, blk=-0.2, tov=0.0),
    _player("bal4", ft_pct=0.9, tpm=0.7, ast=0.4, stl=0.3, pts=0.5, fg_pct=0.2, reb=-0.3, blk=-0.5, tov=0.1),
    _player("bal5", ft_pct=0.4, tpm=0.2, ast=0.2, stl=0.1, pts=0.1, fg_pct=0.0, reb=0.0, blk=0.0, tov=0.0),
    _player("bal6", ft_pct=0.3, tpm=0.4, ast=0.3, stl=0.2, pts=0.2, fg_pct=0.1, reb=-0.1, blk=-0.1, tov=0.1),
    _player("bal7", ft_pct=0.7, tpm=0.5, ast=0.5, stl=0.3, pts=0.3, fg_pct=0.1, reb=-0.2, blk=-0.3, tov=0.1),
    _player("bal8", ft_pct=0.6, tpm=0.3, ast=0.4, stl=0.2, pts=0.2, fg_pct=0.0, reb=-0.1, blk=-0.2, tov=0.0),
    _player("bal9", ft_pct=0.5, tpm=0.4, ast=0.3, stl=0.1, pts=0.1, fg_pct=0.1, reb=0.0, blk=-0.1, tov=0.1),
]
_REALISTIC_POOL = _REALISTIC_BIGS + _REALISTIC_BALANCED
_REALISTIC_CONFIG = LeagueConfig(num_teams=10, roster_slots=(("UTIL", 13),))

# a balanced guard for R3 (strong ast/stl/tpm/ft_pct, weak reb/blk/fg_pct --
# the archetypal complement to the bigs), added to the roster to shrink the
# margin protecting the ft_pct-first ranking (per-category normalization must
# hold up here, not just on an all-bigs roster)
_BALANCED_GUARD = _player(
    "guard1", ft_pct=0.9, tpm=0.8, ast=1.2, stl=0.6, pts=0.3, fg_pct=-0.2, reb=-0.9, blk=-0.7, tov=0.3,
)


def test_realistic_pool_r1_two_bigs_ft_punt_ranks_first_pinned():
    # R1: roster = 2 elite bad-FT bigs. Values below are the engine's own
    # deterministic output for this pool/roster/config (pure function, no
    # randomness) -- pinned as a regression guard on the normalized formula,
    # reported to the controller alongside R2/R3 in the same table.
    roster = [_REALISTIC_BIGS[0], _REALISTIC_BIGS[1]]
    suggestions = suggest_punt_builds(roster, _REALISTIC_POOL, _REALISTIC_CONFIG, limit=5)

    assert suggestions[0].punt_ordered == ("ft_pct", "tpm")
    assert suggestions[0].score == pytest.approx(0.273889, abs=TOL)
    assert suggestions[0].improvement == pytest.approx(0.444444, abs=TOL)
    assert suggestions[0].pool_delta == pytest.approx(-0.041111, abs=TOL)
    assert "ft_pct" in suggestions[0].punt

    single_ft = next(s for s in suggestions if s.punt == frozenset({"ft_pct"}))
    assert single_ft.score == pytest.approx(0.217639, abs=TOL)
    assert single_ft.improvement == pytest.approx(0.256944, abs=TOL)
    assert single_ft.pool_delta == pytest.approx(-0.078611, abs=TOL)


def test_realistic_pool_r3_bigs_plus_balanced_guard_ft_punt_ranks_first_pinned():
    # R3: roster = 2 bigs + 1 balanced guard -- the case that FAILED before
    # per-category normalization (an ordinary balanced player on the roster
    # used to flip the top suggestion to "punt tov").
    roster = [_REALISTIC_BIGS[0], _REALISTIC_BIGS[1], _BALANCED_GUARD]
    suggestions = suggest_punt_builds(roster, _REALISTIC_POOL, _REALISTIC_CONFIG, limit=5)

    assert suggestions[0].punt == frozenset({"ft_pct"})
    assert suggestions[0].score == pytest.approx(0.105139, abs=TOL)
    assert suggestions[0].improvement == pytest.approx(0.144444, abs=TOL)
    assert suggestions[0].pool_delta == pytest.approx(-0.078611, abs=TOL)


def test_tov_and_stl_never_outrank_an_ft_pct_punt_for_poor_ft_bigs_rosters():
    # across all three poor-FT-bigs roster variants, a punt drawn only from
    # {tov, stl} (the least fantasy-relevant categories for this archetype)
    # must never outscore the best ft_pct-containing candidate -- otherwise
    # the advisor would recommend punting the WRONG category for this team
    rosters = {
        "R1 (2 bigs)": [_REALISTIC_BIGS[0], _REALISTIC_BIGS[1]],
        "R2 (3 bigs)": [_REALISTIC_BIGS[0], _REALISTIC_BIGS[1], _REALISTIC_BIGS[2]],
        "R3 (2 bigs + guard)": [_REALISTIC_BIGS[0], _REALISTIC_BIGS[1], _BALANCED_GUARD],
    }
    for label, roster in rosters.items():
        suggestions = suggest_punt_builds(roster, _REALISTIC_POOL, _REALISTIC_CONFIG, limit=20)
        ft_scores = [s.score for s in suggestions if "ft_pct" in s.punt]
        tov_stl_only_scores = [s.score for s in suggestions if s.punt <= {"tov", "stl"}]
        assert ft_scores, f"{label}: expected at least one ft_pct-containing candidate"
        if tov_stl_only_scores:
            assert max(tov_stl_only_scores) < max(ft_scores), label


def test_puntsuggestion_is_frozen_dataclass():
    s = PuntSuggestion(
        punt=frozenset({"ft_pct"}),
        punt_ordered=("ft_pct",),
        score=1.0,
        improvement=0.5,
        pool_delta=0.2,
        weakest="ft_pct",
        weakest_mean=-1.0,
        rationale="x",
    )
    with pytest.raises(FrozenInstanceError):
        s.score = 2.0  # type: ignore[misc]
