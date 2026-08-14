from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from ninecat.engine.streaming import (
    NOTE_NO_GAMES_IN_WINDOW,
    NOTE_NO_POSITIVE_VALUE_REMAINING,
    StreamCandidate,
    StreamPlan,
    StreamSlot,
    plan_streaming,
)

DAY1 = date(2024, 1, 1)
DAY2 = date(2024, 1, 2)
DAY3 = date(2024, 1, 3)
DAY4 = date(2024, 1, 4)

PTS_ONLY = frozenset({"pts"})


# --- back-to-back beats a single game, hand-computed -------------------------


def test_back_to_back_outranks_equal_rate_single_game():
    # both candidates rate pts=1.0/game, close_categories={pts}, window day1-3.
    # b2b @ day1: games_added = 2 (day1,day2 both >= day1) -> value = 1.0*2 = 2.0
    # one  @ day1: games_added = 1 (only day1)              -> value = 1.0*1 = 1.0
    # 2.0 > 1.0 -> b2b wins the single available add despite an identical rate
    b2b = StreamCandidate(player_key="b2b", game_dates=(DAY1, DAY2), category_rates={"pts": 1.0})
    one = StreamCandidate(player_key="one", game_dates=(DAY1,), category_rates={"pts": 1.0})

    plan = plan_streaming(
        [b2b, one], PTS_ONLY, DAY1, DAY3, adds_available=1, reserve_last_day=False
    )

    assert plan.slots == (
        StreamSlot(
            day=DAY1,
            player_key="b2b",
            games_added=2,
            categories_helped=("pts",),
            reason=("category:pts", "back_to_back"),
        ),
    )
    assert plan.adds_used == 1
    assert plan.adds_reserved == 0


# --- a category outside close_categories contributes zero --------------------


def test_locked_category_contributes_nothing():
    # monster: reb=10.0 (NOT close) + pts=0.1 (close) -> value = 0.1*1 = 0.1
    # modest:  pts=0.5 (close) only                    -> value = 0.5*1 = 0.5
    # modest wins despite monster's huge reb rate, because reb is locked/not close
    monster = StreamCandidate(
        player_key="monster", game_dates=(DAY1,), category_rates={"reb": 10.0, "pts": 0.1}
    )
    modest = StreamCandidate(player_key="modest", game_dates=(DAY1,), category_rates={"pts": 0.5})

    plan = plan_streaming(
        [monster, modest], PTS_ONLY, DAY1, DAY3, adds_available=1, reserve_last_day=False
    )

    assert len(plan.slots) == 1
    assert plan.slots[0].player_key == "modest"
    assert plan.slots[0].categories_helped == ("pts",)


# --- budget and reservation ---------------------------------------------------


def test_budget_never_exceeded_and_reservation_reflected():
    # 3 candidates, one game each on distinct days, all score/games_added tie
    # (1.0*1 = 1.0 each) -> tie-break is earliest day first: p1(day1), p2(day2)
    # win the 2 spendable adds; p3(day3) misses out because 1 add is reserved
    p1 = StreamCandidate(player_key="p1", game_dates=(DAY1,), category_rates={"pts": 1.0})
    p2 = StreamCandidate(player_key="p2", game_dates=(DAY2,), category_rates={"pts": 1.0})
    p3 = StreamCandidate(player_key="p3", game_dates=(DAY3,), category_rates={"pts": 1.0})

    plan = plan_streaming(
        [p1, p2, p3], PTS_ONLY, DAY1, DAY3, adds_available=3, reserve_last_day=True
    )

    assert plan.adds_reserved == 1
    assert plan.adds_used == 2
    assert len(plan.slots) == 2
    assert plan.adds_used <= 3  # budget never exceeded
    assert [s.player_key for s in plan.slots] == ["p1", "p2"]
    assert [s.day for s in plan.slots] == [DAY1, DAY2]


def test_reserve_last_day_with_single_add_still_produces_a_slot():
    # adds_available == 1 -> reservation must not starve the plan: pin that
    # reserve_last_day=True still yields adds_reserved=0 and one real slot
    p1 = StreamCandidate(player_key="p1", game_dates=(DAY1,), category_rates={"pts": 1.0})

    plan = plan_streaming([p1], PTS_ONLY, DAY1, DAY3, adds_available=1, reserve_last_day=True)

    assert plan.adds_reserved == 0
    assert plan.adds_used == 1
    assert len(plan.slots) == 1
    assert plan.slots[0].player_key == "p1"


def test_never_selects_the_same_player_twice():
    # one candidate playing 2 games in the window, budget=5 -> only ONE slot
    # is ever produced (a player can't be added twice), pinned at their
    # highest-value day (day1: games_added=2) not their weaker day2 entry
    solo = StreamCandidate(player_key="solo", game_dates=(DAY1, DAY2), category_rates={"pts": 1.0})

    plan = plan_streaming([solo], PTS_ONLY, DAY1, DAY3, adds_available=5, reserve_last_day=False)

    assert len(plan.slots) == 1
    assert plan.slots[0] == StreamSlot(
        day=DAY1,
        player_key="solo",
        games_added=2,
        categories_helped=("pts",),
        reason=("category:pts", "back_to_back"),
    )
    assert plan.adds_used == 1


# --- categories_helped / reason: canonical order, positive-rate only ---------


def test_categories_helped_is_canonical_order_and_positive_rate_only():
    # CATEGORIES order is (fg_pct, ft_pct, tpm, pts, reb, ast, stl, blk, tov):
    # pts (index 3) must sort before ast (index 5) in categories_helped
    # regardless of dict/frozenset construction order. ast rate is 0.0 (not
    # positive) and stl rate is negative -> both close but neither "helped".
    p = StreamCandidate(
        player_key="p",
        game_dates=(DAY1,),
        category_rates={"ast": 2.0, "pts": 1.0, "stl": -0.5, "reb": 0.0},
    )
    close = frozenset({"stl", "ast", "pts", "reb"})

    plan = plan_streaming([p], close, DAY1, DAY1, adds_available=1, reserve_last_day=False)

    assert len(plan.slots) == 1
    slot = plan.slots[0]
    assert slot.categories_helped == ("pts", "ast")
    assert slot.reason == ("category:pts", "category:ast")  # not a back-to-back day


# --- turnovers are a cost, never a benefit ------------------------------------


def test_high_turnover_candidate_scores_lower_than_low_turnover_otherwise_identical():
    # both play 1 game on day1, both pts=16.0/game (identical counting gain,
    # scaled by CATEGORY_SCALE["pts"]=10.0 -> 1.6 each -- large enough to
    # keep BOTH candidates net-positive despite tov's cost, so the worth-it
    # gate doesn't swallow one of them and hide the comparison); only tov
    # rate differs. tov contributes NEGATIVELY and is scaled by
    # CATEGORY_SCALE["tov"]=1.5, so:
    #   low_tov:  pts(1.6) + tov(-(0.3/1.5)) = 1.6 - 0.2    = 1.4
    #   high_tov: pts(1.6) + tov(-(2.0/1.5)) = 1.6 - 1.3333 = 0.2667
    # 1.4 > 0.2667 -> low_tov must be picked first even though pts is
    # identical. tov rates are chosen straddling LOW_TOV_RATE (1.5): low's
    # 0.3 is below it (genuinely helps tov), high's 2.0 is at/above it
    # (does not) -- see engine.contribution.helps_category.
    low_tov = StreamCandidate(
        player_key="low_tov", game_dates=(DAY1,), category_rates={"pts": 16.0, "tov": 0.3}
    )
    high_tov = StreamCandidate(
        player_key="high_tov", game_dates=(DAY1,), category_rates={"pts": 16.0, "tov": 2.0}
    )
    close = frozenset({"pts", "tov"})

    plan = plan_streaming(
        [low_tov, high_tov], close, DAY1, DAY1, adds_available=2, reserve_last_day=False
    )

    # both are net-positive, so both are selected, in value order
    assert [s.player_key for s in plan.slots] == ["low_tov", "high_tov"]
    by_key = {s.player_key: s for s in plan.slots}
    # low_tov's rate is below LOW_TOV_RATE -> genuinely helps tov
    assert by_key["low_tov"].categories_helped == ("pts", "tov")
    assert "category:tov" in by_key["low_tov"].reason
    # high_tov's rate is at/above LOW_TOV_RATE -> does not help tov, even
    # though it still costs them the win against low_tov
    assert by_key["high_tov"].categories_helped == ("pts",)
    assert "category:tov" not in by_key["high_tov"].reason


def test_turnover_only_contribution_is_negative_value_and_never_shown_as_helping():
    # a candidate whose only close category is tov: value = -rate*games < 0
    # for any real (non-negative) turnover rate -> never selected, and the
    # plan never claims (via categories_helped/reason) that this player helps
    turnover_prone = StreamCandidate(
        player_key="turnover_prone", game_dates=(DAY1,), category_rates={"tov": 1.5}
    )

    plan = plan_streaming(
        [turnover_prone], frozenset({"tov"}), DAY1, DAY3, adds_available=3, reserve_last_day=False
    )

    assert plan.slots == ()
    assert plan.adds_used == 0
    assert plan.notes == (NOTE_NO_POSITIVE_VALUE_REMAINING,)


def test_net_negative_candidate_is_skipped_even_with_budget_remaining():
    # good: ast(+1.0*1) + tov(-0.2*1) = 0.8  -> net positive, selected
    # bad:  ast(+0.1*1) + tov(-1.0*1) = -0.9 -> net negative (turnover cost
    #       outweighs the counting-stat gain) -> must NEVER be selected, even
    #       though plenty of budget remains after "good" is picked
    good = StreamCandidate(
        player_key="good", game_dates=(DAY1,), category_rates={"ast": 1.0, "tov": 0.2}
    )
    bad = StreamCandidate(
        player_key="bad", game_dates=(DAY1,), category_rates={"ast": 0.1, "tov": 1.0}
    )
    close = frozenset({"ast", "tov"})

    plan = plan_streaming([good, bad], close, DAY1, DAY1, adds_available=5, reserve_last_day=False)

    assert [s.player_key for s in plan.slots] == ["good"]
    assert plan.adds_used == 1
    # 5 adds were available and only 1 spent -- the greedy stopped itself
    # rather than burn budget on "bad", and says so via the note token
    assert plan.notes == (NOTE_NO_POSITIVE_VALUE_REMAINING,)


# --- empty / degenerate inputs: never raise, always a note token -------------


def _one_candidate() -> StreamCandidate:
    return StreamCandidate(player_key="p", game_dates=(DAY1,), category_rates={"pts": 1.0})


def test_empty_candidates_returns_empty_plan_with_note():
    plan = plan_streaming([], PTS_ONLY, DAY1, DAY3, adds_available=3)
    assert plan == StreamPlan(slots=(), adds_used=0, adds_reserved=0, notes=("no_candidates",))


def test_empty_close_categories_returns_empty_plan_with_note():
    plan = plan_streaming([_one_candidate()], frozenset(), DAY1, DAY3, adds_available=3)
    assert plan == StreamPlan(
        slots=(), adds_used=0, adds_reserved=0, notes=("no_close_categories",)
    )


def test_zero_adds_available_returns_empty_plan_with_note():
    plan = plan_streaming([_one_candidate()], PTS_ONLY, DAY1, DAY3, adds_available=0)
    assert plan == StreamPlan(slots=(), adds_used=0, adds_reserved=0, notes=("no_adds_available",))


def test_negative_adds_available_returns_empty_plan_with_note():
    plan = plan_streaming([_one_candidate()], PTS_ONLY, DAY1, DAY3, adds_available=-2)
    assert plan == StreamPlan(slots=(), adds_used=0, adds_reserved=0, notes=("no_adds_available",))


def test_invalid_window_returns_empty_plan_with_note():
    plan = plan_streaming([_one_candidate()], PTS_ONLY, DAY3, DAY1, adds_available=3)
    assert plan == StreamPlan(slots=(), adds_used=0, adds_reserved=0, notes=("invalid_window",))


# --- I4: candidates and close categories exist, but nobody plays in-window ---


def test_no_games_in_window_returns_note_and_no_reservation():
    # candidate exists and close_categories is real, but their only game is
    # OUTSIDE the window -- this used to silently return an empty plan
    # (slots=(), notes=()) while adds_reserved could still claim a
    # reservation was held back from nothing. Now it's a distinct, honest
    # note, and adds_reserved is always 0 here (reserve_last_day=True would
    # otherwise reserve 1 with adds_available=3).
    outside_window = StreamCandidate(
        player_key="p", game_dates=(DAY4,), category_rates={"pts": 1.0}
    )
    plan = plan_streaming(
        [outside_window], PTS_ONLY, DAY1, DAY3, adds_available=3, reserve_last_day=True
    )
    assert plan == StreamPlan(
        slots=(), adds_used=0, adds_reserved=0, notes=(NOTE_NO_GAMES_IN_WINDOW,)
    )


# --- C3: punt beats close, mirroring engine.waivers ---------------------------


def test_punted_category_is_excluded_even_when_close():
    # blk is BOTH close and punted -> must contribute nothing to value or
    # categories_helped, mirroring engine.waivers.score_waiver_candidates'
    # punt-beats-close rule. Without the punt, monster_blk's huge blk rate
    # would dominate; with it, only pts (also close, not punted) counts.
    monster_blk = StreamCandidate(
        player_key="monster_blk", game_dates=(DAY1,), category_rates={"blk": 10.0, "pts": 0.1}
    )
    modest_pts = StreamCandidate(
        player_key="modest_pts", game_dates=(DAY1,), category_rates={"pts": 0.5}
    )
    close = frozenset({"blk", "pts"})

    plan = plan_streaming(
        [monster_blk, modest_pts],
        close,
        DAY1,
        DAY3,
        adds_available=1,
        reserve_last_day=False,
        punt=frozenset({"blk"}),
    )

    assert len(plan.slots) == 1
    assert plan.slots[0].player_key == "modest_pts"
    assert plan.slots[0].categories_helped == ("pts",)


def test_punting_every_close_category_returns_no_close_categories_note():
    # close_categories == punt entirely -> effective close set is empty,
    # same outcome/note as an empty close_categories argument
    plan = plan_streaming(
        [_one_candidate()], PTS_ONLY, DAY1, DAY3, adds_available=3, punt=frozenset({"pts"})
    )
    assert plan == StreamPlan(
        slots=(), adds_used=0, adds_reserved=0, notes=("no_close_categories",)
    )


def test_unknown_punt_category_raises_naming_it():
    with pytest.raises(ValueError, match="bogus"):
        plan_streaming(
            [_one_candidate()], PTS_ONLY, DAY1, DAY3, adds_available=3, punt=frozenset({"bogus"})
        )


# --- I3: per-category scaling makes a category-appropriate specialist win ----


def test_scaled_value_lets_steals_specialist_beat_bigger_raw_scorer():
    # reviewer's exact numbers: a 22-pts/0.4-stl scorer vs a 6-pts/2.5-stl
    # specialist, both categories close, 3 games each. On RAW per-game rates
    # the scorer wins 67.2 to 25.5 purely because points is a numerically
    # bigger category -- CATEGORY_SCALE (pts=10.0, stl=1.0) must flip this:
    #   scorer:      (22/10 + 0.4/1) * 3 = 2.6 * 3 = 7.8
    #   specialist:  (6/10  + 2.5/1) * 3 = 3.1 * 3 = 9.3
    # 9.3 > 7.8 -> the specialist, the actually-correct pick for a
    # steals-close matchup, is chosen over the raw-bigger scorer.
    scorer = StreamCandidate(
        player_key="scorer",
        game_dates=(DAY1, DAY2, DAY3),
        category_rates={"pts": 22.0, "stl": 0.4},
    )
    specialist = StreamCandidate(
        player_key="specialist",
        game_dates=(DAY1, DAY2, DAY3),
        category_rates={"pts": 6.0, "stl": 2.5},
    )
    close = frozenset({"pts", "stl"})

    plan = plan_streaming(
        [scorer, specialist], close, DAY1, DAY3, adds_available=1, reserve_last_day=False
    )

    assert plan.slots[0].player_key == "specialist"


# --- ValueError only for genuinely invalid input ------------------------------


def test_unknown_close_category_raises_naming_it():
    with pytest.raises(ValueError, match="bogus"):
        plan_streaming(
            [_one_candidate()], frozenset({"bogus"}), DAY1, DAY3, adds_available=3
        )


def test_unknown_category_rates_key_raises_naming_it_and_player():
    bad = StreamCandidate(player_key="bad_player", game_dates=(DAY1,), category_rates={"bogus_stat": 1.0})
    with pytest.raises(ValueError, match="bad_player"):
        plan_streaming([bad], PTS_ONLY, DAY1, DAY3, adds_available=3)


# --- determinism ---------------------------------------------------------------


def test_identical_inputs_produce_identical_plans():
    p1 = StreamCandidate(player_key="p1", game_dates=(DAY1, DAY2), category_rates={"pts": 1.0})
    p2 = StreamCandidate(player_key="p2", game_dates=(DAY2, DAY3), category_rates={"ast": 0.7})
    close = frozenset({"pts", "ast"})

    plan_a = plan_streaming([p1, p2], close, DAY1, DAY4, adds_available=2, reserve_last_day=True)
    plan_b = plan_streaming([p1, p2], close, DAY1, DAY4, adds_available=2, reserve_last_day=True)

    assert plan_a == plan_b


# --- frozen dataclasses ---------------------------------------------------------


def test_streamslot_and_streamplan_are_frozen():
    slot = StreamSlot(day=DAY1, player_key="p", games_added=1, categories_helped=("pts",), reason=())
    plan = StreamPlan(slots=(slot,), adds_used=1, adds_reserved=0, notes=())
    with pytest.raises(FrozenInstanceError):
        slot.games_added = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.adds_used = 2  # type: ignore[misc]
