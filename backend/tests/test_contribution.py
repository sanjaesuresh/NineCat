from datetime import date

import pytest

from ninecat.engine.contribution import (
    CATEGORY_SCALE,
    LOW_TOV_RATE,
    category_reason_token,
    helps_category,
    is_worth_it,
    scaled_contribution,
    signed_contribution,
)
from ninecat.engine.streaming import StreamCandidate, plan_streaming
from ninecat.engine.waivers import WaiverCandidate, score_waiver_candidates
from ninecat.engine.zscores import CATEGORIES

TOL = 1e-9

DAY = date(2024, 1, 1)


# --- signed_contribution: the sign rule ---------------------------------------


def test_signed_contribution_negates_tov_only():
    assert signed_contribution("tov", 2.0) == -2.0
    for cat in CATEGORIES:
        if cat != "tov":
            assert signed_contribution(cat, 2.0) == 2.0


# --- scaled_contribution: divides by the category's fixed scale ---------------


def test_scaled_contribution_divides_signed_contribution_by_category_scale():
    assert scaled_contribution("pts", 20.0) == pytest.approx(
        20.0 / CATEGORY_SCALE["pts"], abs=TOL
    )
    assert scaled_contribution("tov", 3.0) == pytest.approx(-3.0 / CATEGORY_SCALE["tov"], abs=TOL)


def test_every_category_has_a_positive_scale_factor():
    # every CATEGORIES key must be scalable, or scaled_contribution raises a
    # KeyError the first time a caller passes that category
    assert set(CATEGORY_SCALE) == set(CATEGORIES)
    assert all(v > 0.0 for v in CATEGORY_SCALE.values())


def test_scaled_contribution_lets_steals_specialist_beat_bigger_raw_scorer():
    # I3, pinned directly at the primitive: reviewer's exact numbers -- a
    # 22-pts/0.4-stl scorer vs a 6-pts/2.5-stl specialist, 3 games each, both
    # categories close. On RAW units the scorer wins 67.2 to 25.5 (points is
    # a numerically bigger category) -- scaled_contribution must flip this,
    # because the specialist is the actually-correct pick for a
    # steals-close matchup.
    games = 3
    scorer = sum(scaled_contribution(c, r) for c, r in {"pts": 22.0, "stl": 0.4}.items()) * games
    specialist = (
        sum(scaled_contribution(c, r) for c, r in {"pts": 6.0, "stl": 2.5}.items()) * games
    )
    assert specialist > scorer
    assert specialist == pytest.approx(9.3, abs=TOL)
    assert scorer == pytest.approx(7.8, abs=TOL)


# --- is_worth_it: the C2 gate ---------------------------------------------------


def test_is_worth_it_requires_strictly_positive():
    assert is_worth_it(0.01) is True
    assert is_worth_it(0.0) is False
    assert is_worth_it(-0.01) is False


# --- helps_category: the unified tov rule (C2 + token-vocabulary alignment) ---


def test_helps_category_tov_requires_a_low_rate():
    assert helps_category("tov", 0.5, games_remaining=2.0) is True
    # boundary is exclusive: a rate AT LOW_TOV_RATE does not count as low
    assert helps_category("tov", LOW_TOV_RATE, games_remaining=2.0) is False
    assert helps_category("tov", 5.0, games_remaining=2.0) is False


def test_helps_category_tov_requires_games_remaining():
    # C2: a player who does not play does not help your turnovers, no
    # matter how low their rate reads
    assert helps_category("tov", 0.1, games_remaining=0.0) is False
    assert helps_category("tov", 0.1, games_remaining=0.001) is True


def test_helps_category_non_tov_just_needs_a_positive_rate():
    # non-tov categories are never gated on games_remaining here -- a zero-
    # games candidate's raw rate contributes nothing to VALUE regardless
    # (games multiplies the whole contribution upstream), so this function
    # only needs to judge the rate itself
    assert helps_category("pts", 0.1, games_remaining=0.0) is True
    assert helps_category("pts", 0.0, games_remaining=5.0) is False


def test_category_reason_token_format():
    assert category_reason_token("blk") == "category:blk"


# --- cross-module agreement: the actual point of this pass ---------------------


def test_streaming_and_waivers_agree_on_sign_worth_it_and_tov_helped():
    """The same candidate, scored by both engines against the same close
    category set, must agree on: whether they're worth recommending at all
    (both engines drop net-non-positive candidates, C2), and whether tov
    counts as "helped" (both apply the shared low-rate + games-remaining
    rule) -- the structural finding this whole fix pass exists to close."""
    close = frozenset({"pts", "tov"})

    # net-negative candidate (turnover cost exceeds the points gain, pts=1.0
    # tov=5.0): NEITHER engine should ever recommend this player
    bad_rates = {"pts": 1.0, "tov": 5.0}
    stream_bad = StreamCandidate(player_key="p", game_dates=(DAY,), category_rates=bad_rates)
    waiver_bad = WaiverCandidate(
        player_key="p", games_remaining=1.0, rates=bad_rates, stat_basis="projection"
    )

    stream_plan_bad = plan_streaming([stream_bad], close, DAY, DAY, adds_available=3)
    waiver_result_bad = score_waiver_candidates([waiver_bad], close, [])

    assert stream_plan_bad.slots == ()
    assert waiver_result_bad == ()

    # net-positive, LOW tov rate (pts=10.0, tov=0.2): BOTH engines must tag
    # tov as helped, using the identical low-rate rule
    good_rates = {"pts": 10.0, "tov": 0.2}
    stream_good = StreamCandidate(player_key="q", game_dates=(DAY,), category_rates=good_rates)
    waiver_good = WaiverCandidate(
        player_key="q", games_remaining=1.0, rates=good_rates, stat_basis="projection"
    )

    stream_plan_good = plan_streaming([stream_good], close, DAY, DAY, adds_available=3)
    waiver_result_good = score_waiver_candidates([waiver_good], close, [])

    assert len(stream_plan_good.slots) == 1
    assert len(waiver_result_good) == 1
    assert "tov" in stream_plan_good.slots[0].categories_helped
    assert "tov" in waiver_result_good[0].categories_helped
    assert "category:tov" in stream_plan_good.slots[0].reason
    assert "category:tov" in waiver_result_good[0].reasons

    # net-positive, but HIGH tov rate (pts=20.0, tov=2.0, still >= 1.5 --
    # pts is large enough to keep the total net-positive despite the cost):
    # both engines score this positively (worth-it), but NEITHER tags tov
    # as helped
    mixed_rates = {"pts": 20.0, "tov": 2.0}
    stream_mixed = StreamCandidate(player_key="r", game_dates=(DAY,), category_rates=mixed_rates)
    waiver_mixed = WaiverCandidate(
        player_key="r", games_remaining=1.0, rates=mixed_rates, stat_basis="projection"
    )

    stream_plan_mixed = plan_streaming([stream_mixed], close, DAY, DAY, adds_available=3)
    waiver_result_mixed = score_waiver_candidates([waiver_mixed], close, [])

    assert len(stream_plan_mixed.slots) == 1
    assert len(waiver_result_mixed) == 1
    assert "tov" not in stream_plan_mixed.slots[0].categories_helped
    assert "tov" not in waiver_result_mixed[0].categories_helped
