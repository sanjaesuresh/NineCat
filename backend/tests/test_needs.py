import pytest

from ninecat.engine.needs import NEED_MILD_Z, NEED_STRONG_Z, need_weights
from ninecat.engine.zscores import CATEGORIES

TOL = 1e-9


def _roster(**overrides: float) -> list[dict[str, float]]:
    """A single-player roster (mean == that player's own z) with all nine
    categories defaulting to 0.0; pass only the ones a hand-computed case
    cares about."""
    z = {c: 0.0 for c in CATEGORIES}
    z.update(overrides)
    return [z]


# --- boundary/tier pinning (single-player roster -> mean == the value passed) --
#
# extracted unchanged from draft_sim.py's private _need_weights:
#   roster_mean <= NEED_STRONG_Z (-0.35)                 -> 0.5  (INCLUSIVE <=)
#   NEED_STRONG_Z < roster_mean < NEED_MILD_Z (0.0)       -> 0.25 (EXCLUSIVE <)
#   roster_mean >= NEED_MILD_Z (0.0)                      -> 0.0


def test_well_below_strong_threshold_weights_0_5():
    weights = need_weights(_roster(reb=-2.0))
    assert weights["reb"] == pytest.approx(0.5, abs=TOL)


def test_at_strong_threshold_boundary_is_inclusive_weights_0_5():
    # -0.35 exactly: original used <=, so this must still be the strong tier
    weights = need_weights(_roster(reb=NEED_STRONG_Z))
    assert weights["reb"] == pytest.approx(0.5, abs=TOL)


def test_between_strong_and_mild_thresholds_weights_0_25():
    weights = need_weights(_roster(reb=-0.2))
    assert weights["reb"] == pytest.approx(0.25, abs=TOL)


def test_at_mild_threshold_boundary_is_exclusive_weights_0():
    # 0.0 exactly: original used a strict "< 0" for the mild tier, so exactly
    # 0.0 must fall through to the "otherwise" 0.0 tier, not 0.25
    weights = need_weights(_roster(reb=NEED_MILD_Z))
    assert weights["reb"] == pytest.approx(0.0, abs=TOL)


def test_positive_mean_weights_0():
    weights = need_weights(_roster(reb=1.0))
    assert weights["reb"] == pytest.approx(0.0, abs=TOL)


def test_punted_category_forced_to_0_regardless_of_mean():
    # reb mean is well into the "strong need" tier, but punting it must force
    # the weight to 0 regardless of how weak the roster actually is there
    weights = need_weights(_roster(reb=-5.0), punt=frozenset({"reb"}))
    assert weights["reb"] == pytest.approx(0.0, abs=TOL)


# --- full return shape ----------------------------------------------------


def test_returns_a_weight_for_every_category():
    weights = need_weights(_roster(reb=-1.0, ast=-0.1, stl=1.0))
    assert set(weights.keys()) == set(CATEGORIES)
    assert weights["reb"] == pytest.approx(0.5, abs=TOL)
    assert weights["ast"] == pytest.approx(0.25, abs=TOL)
    assert weights["stl"] == pytest.approx(0.0, abs=TOL)
    # every untouched category defaults to 0.0 mean -> weight 0
    for cat in CATEGORIES:
        if cat not in ("reb", "ast", "stl"):
            assert weights[cat] == pytest.approx(0.0, abs=TOL)


def test_empty_roster_gives_all_zero_weights():
    # no basis for need with no players -> every weight 0, which is what lets
    # a downstream caller (draft board, waiver scorer) fall through to pure
    # value ranking
    weights = need_weights([])
    assert weights == {cat: 0.0 for cat in CATEGORIES}


def test_mean_is_averaged_across_multiple_players():
    # two players: reb z of -1.0 and 0.3 -> mean = -0.35 exactly -> strong tier
    roster = [
        {**{c: 0.0 for c in CATEGORIES}, "reb": -1.0},
        {**{c: 0.0 for c in CATEGORIES}, "reb": 0.3},
    ]
    weights = need_weights(roster)
    assert weights["reb"] == pytest.approx(0.5, abs=TOL)


# --- validation -------------------------------------------------------------


def test_unknown_punt_category_raises_value_error_naming_it():
    with pytest.raises(ValueError, match="bogus_cat"):
        need_weights(_roster(reb=-1.0), punt=frozenset({"bogus_cat"}))
