import pytest

from ninecat.engine.waivers import (
    CLOSE_CATEGORY_WEIGHT,
    LOW_TOV_RATE,
    SCHEDULE_EDGE_GAMES,
    WaiverCandidate,
    score_waiver_candidates,
)
from ninecat.engine.zscores import CATEGORIES

TOL = 1e-9

# a roster with no players has no basis for "need" (need_weights returns all
# 0.0), isolating each test's weight source to whatever close_categories/punt
# it passes explicitly, unless a test says otherwise
NO_NEEDS: list[dict[str, float]] = []


def _zero_dict(**overrides: float) -> dict[str, float]:
    d = {cat: 0.0 for cat in CATEGORIES}
    d.update(overrides)
    return d


# --- headline: schedule beats per-game quality --------------------------------


def test_four_game_streamer_outranks_better_one_game_player():
    # close_categories={"pts"} -> weight[pts] = 0.0 (no needs) + 1.0 (close) = 1.0;
    # every other category has weight 0. Contribution is SCALED (I3):
    # scaled_contribution divides by CATEGORY_SCALE["pts"] == 10.0.
    # streamer: games_remaining=4, pts rate 1.0/game -> score = 1.0 * (1.0/10) * 4 = 0.4
    # better:   games_remaining=1, pts rate 3.0/game -> score = 1.0 * (3.0/10) * 1 = 0.3
    # 0.4 > 0.3 despite better's per-game rate being 3x higher: games dominate.
    streamer = WaiverCandidate(
        player_key="streamer", games_remaining=4.0, rates={"pts": 1.0}, stat_basis="projection"
    )
    better = WaiverCandidate(
        player_key="better", games_remaining=1.0, rates={"pts": 3.0}, stat_basis="projection"
    )

    result = score_waiver_candidates([streamer, better], frozenset({"pts"}), NO_NEEDS)

    assert [r.player_key for r in result] == ["streamer", "better"]
    assert result[0].score == pytest.approx(0.4, abs=TOL)
    assert result[1].score == pytest.approx(0.3, abs=TOL)
    # mean games_remaining across the batch is (4+1)/2 = 2.5; the token
    # requires clearing mean + SCHEDULE_EDGE_GAMES (1.0) = 3.5. streamer's 4
    # clears it (their schedule is legibly doing the work), better's 1 does not
    assert "schedule_driven" in result[0].reasons
    assert "schedule_driven" not in result[1].reasons
    assert result[0].categories_helped == ("pts",)


def test_schedule_driven_requires_a_full_game_above_the_mean_not_just_above_it():
    # baseline: games_remaining=2.0, barely_above: games_remaining=2.6.
    # mean = (2.0 + 2.6) / 2 = 2.3; the OLD "merely above the mean" rule
    # would have flagged barely_above (2.6 > 2.3). The threshold now requires
    # mean + SCHEDULE_EDGE_GAMES (1.0) = 3.3, which neither candidate reaches,
    # so the token must not fire for either -- pins the noise fix directly.
    baseline = WaiverCandidate(
        player_key="baseline", games_remaining=2.0, rates={"pts": 1.0}, stat_basis="projection"
    )
    barely_above = WaiverCandidate(
        player_key="barely_above",
        games_remaining=2.6,
        rates={"pts": 1.0},
        stat_basis="projection",
    )

    result = score_waiver_candidates([baseline, barely_above], frozenset({"pts"}), NO_NEEDS)
    by_key = {r.player_key: r for r in result}

    assert "schedule_driven" not in by_key["baseline"].reasons
    assert "schedule_driven" not in by_key["barely_above"].reasons


def test_schedule_edge_games_constant():
    assert SCHEDULE_EDGE_GAMES == 1.0


# --- locked category (not close, not a need) contributes nothing --------------


def test_strong_contributor_in_locked_category_scores_below_modest_in_close_one():
    # close_categories={"ast"} only -> weight[ast] = 1.0, weight[reb] = 0.0.
    # strong_wrong_cat: reb rate 20.0, weight 0 -> score = 0.0 * ... = 0.0
    # modest_right_cat: ast rate 1.0, weight 1.0, CATEGORY_SCALE["ast"]=3.0
    #   -> score = 1.0 * (1.0/3.0) * 1 = 0.3333...
    # C2: a score at or below zero is never a recommendation, so
    # strong_wrong_cat (score exactly 0.0) is dropped entirely rather than
    # merely out-ranked -- there is nothing here worth telling the user
    # about, not even as a last-place suggestion.
    strong_wrong_cat = WaiverCandidate(
        player_key="strong_wrong_cat",
        games_remaining=1.0,
        rates={"reb": 20.0},
        stat_basis="projection",
    )
    modest_right_cat = WaiverCandidate(
        player_key="modest_right_cat",
        games_remaining=1.0,
        rates={"ast": 1.0},
        stat_basis="projection",
    )

    result = score_waiver_candidates(
        [strong_wrong_cat, modest_right_cat], frozenset({"ast"}), NO_NEEDS
    )

    assert [r.player_key for r in result] == ["modest_right_cat"]
    assert result[0].score == pytest.approx(1.0 / 3.0, abs=TOL)


# --- punt beats close (the subtlest rule) --------------------------------------


def test_punt_beats_close_forces_zero_weight():
    # blk is BOTH close and punted -> weight[blk] = (0.0 + 1.0) then zeroed by
    # punt = 0.0. pts is close but not punted -> weight[pts] = 1.0, giving the
    # call an overall basis (not the all-zero-weight empty-tuple case).
    # blocker_only has a real blk rate but no pts rate, so their score comes
    # ENTIRELY from the punted-but-close category, which is worth zero:
    #   score = weight[blk](0.0) * scaled(blk,5.0) * 1 + weight[pts](1.0) * scaled(pts,0.0) * 1 = 0.0
    # C2's worth-it gate then drops a 0.0 score entirely -- not merely
    # "helps nothing", genuinely excluded from the result.
    blocker_only = WaiverCandidate(
        player_key="blocker_only", games_remaining=1.0, rates={"blk": 5.0}, stat_basis="projection"
    )

    result = score_waiver_candidates(
        [blocker_only], frozenset({"blk", "pts"}), NO_NEEDS, punt=frozenset({"blk"})
    )

    assert result == ()

    # sanity check that the punt, not something else, caused the exclusion:
    # WITHOUT the punt, blk is simply close (weight 1.0) and this same
    # candidate scores positively on it and appears, helping blk only
    # (their pts rate is 0.0, so pts is never "helped")
    unpunted = score_waiver_candidates([blocker_only], frozenset({"blk", "pts"}), NO_NEEDS)
    assert len(unpunted) == 1
    assert unpunted[0].score == pytest.approx(10.0, abs=TOL)
    assert unpunted[0].categories_helped == ("blk",)


# --- turnovers are a cost, never a benefit -------------------------------------


def test_high_turnover_candidate_scores_lower_than_low_turnover_twin():
    # close_categories={"pts", "tov"} -> weight[pts] = weight[tov] = 1.0.
    # Both candidates carry the SAME large pts rate (40.0/game -- scaled by
    # CATEGORY_SCALE["pts"]=10.0 -> 4.0), just large enough that BOTH stay
    # net-positive despite tov's cost (the C2 worth-it gate would otherwise
    # drop a tov-only comparison entirely, since tov's contribution is
    # always <= 0 in isolation -- see the module docstring). Only tov
    # differs, isolating its cost:
    #   high_to: pts(4.0) + tov(-(5.0/1.5)) = 4.0 - 3.3333 = 0.6667
    #   low_to:  pts(4.0) + tov(-(0.5/1.5)) = 4.0 - 0.3333 = 3.6667
    # 3.6667 > 0.6667, so low_to outranks high_to: adding turnovers only
    # ever costs, even with an identical (and dominant) pts contribution.
    high_to = WaiverCandidate(
        player_key="high_to",
        games_remaining=1.0,
        rates={"pts": 40.0, "tov": 5.0},
        stat_basis="projection",
    )
    low_to = WaiverCandidate(
        player_key="low_to",
        games_remaining=1.0,
        rates={"pts": 40.0, "tov": 0.5},
        stat_basis="projection",
    )

    result = score_waiver_candidates([high_to, low_to], frozenset({"pts", "tov"}), NO_NEEDS)

    assert [r.player_key for r in result] == ["low_to", "high_to"]
    assert result[0].score == pytest.approx(4.0 - 0.5 / 1.5, abs=TOL)
    assert result[1].score == pytest.approx(4.0 - 5.0 / 1.5, abs=TOL)
    # high_to's rate (5.0) is not below LOW_TOV_RATE (1.5) -> never "helps" tov
    assert "category:tov" not in result[1].reasons
    assert "tov" not in result[1].categories_helped
    # low_to's rate (0.5) is below LOW_TOV_RATE -> genuinely helps tov
    assert "category:tov" in result[0].reasons
    assert "tov" in result[0].categories_helped


def test_low_tov_rate_constant_is_the_helped_threshold():
    assert LOW_TOV_RATE == 1.5


# --- need + close weights combine additively -----------------------------------


def test_category_weight_combines_need_and_close_additively():
    # roster mean reb z = -1.0, at/below NEED_STRONG_Z (-0.35) -> need weight
    # 0.5 for reb. reb is also close -> + CLOSE_CATEGORY_WEIGHT (1.0).
    # weight[reb] = 0.5 + 1.0 = 1.5; every other category has 0 (mean 0.0 is
    # not < NEED_MILD_Z, and nothing else is close). CATEGORY_SCALE["reb"] =
    # 4.0, so candidate: reb rate 2.0, games_remaining=1
    #   -> score = 1.5 * (2.0/4.0) * 1 = 0.75
    roster = [_zero_dict(reb=-1.0)]
    candidate = WaiverCandidate(
        player_key="rebounder", games_remaining=1.0, rates={"reb": 2.0}, stat_basis="projection"
    )

    result = score_waiver_candidates([candidate], frozenset({"reb"}), roster)

    assert len(result) == 1
    assert result[0].score == pytest.approx(0.75, abs=TOL)
    assert result[0].categories_helped == ("reb",)


# --- no-basis and empty-input both yield an empty tuple, not a ranking --------


def test_empty_candidates_returns_empty_tuple():
    assert score_waiver_candidates([], frozenset({"pts"}), NO_NEEDS) == ()


def test_no_close_categories_and_no_needs_returns_empty_tuple():
    candidate = WaiverCandidate(
        player_key="anyone", games_remaining=2.0, rates={"pts": 10.0}, stat_basis="projection"
    )
    # nothing close, no roster needs, no punt -> every category weight is 0.0
    assert score_waiver_candidates([candidate], frozenset(), NO_NEEDS) == ()


# --- validation ------------------------------------------------------------


def test_negative_games_remaining_raises_naming_player():
    bad = WaiverCandidate(
        player_key="negative_games", games_remaining=-1.0, rates={}, stat_basis="projection"
    )
    with pytest.raises(ValueError, match="negative_games"):
        score_waiver_candidates([bad], frozenset({"pts"}), NO_NEEDS)


def test_unknown_close_category_raises_naming_it():
    candidate = WaiverCandidate(
        player_key="p", games_remaining=1.0, rates={"pts": 1.0}, stat_basis="projection"
    )
    with pytest.raises(ValueError, match="threes"):
        score_waiver_candidates([candidate], frozenset({"threes"}), NO_NEEDS)


def test_unknown_category_in_rates_raises_naming_player_and_category():
    bad = WaiverCandidate(
        player_key="bad_rates", games_remaining=1.0, rates={"threes": 1.0}, stat_basis="projection"
    )
    with pytest.raises(ValueError, match="bad_rates"):
        score_waiver_candidates([bad], frozenset({"pts"}), NO_NEEDS)


def test_unknown_punt_category_raises():
    candidate = WaiverCandidate(
        player_key="p", games_remaining=1.0, rates={"pts": 1.0}, stat_basis="projection"
    )
    with pytest.raises(ValueError, match="not_a_category"):
        score_waiver_candidates(
            [candidate], frozenset({"pts"}), NO_NEEDS, punt=frozenset({"not_a_category"})
        )


def test_limit_less_than_one_raises():
    candidate = WaiverCandidate(
        player_key="p", games_remaining=1.0, rates={"pts": 1.0}, stat_basis="projection"
    )
    with pytest.raises(ValueError, match="limit"):
        score_waiver_candidates([candidate], frozenset({"pts"}), NO_NEEDS, limit=0)


# --- limit and tie-break ----------------------------------------------------


def test_limit_caps_result_length_to_the_top_scorers():
    # three candidates, distinct pts rates -> distinct scores; limit=2 keeps
    # only the top 2, in descending score order
    low = WaiverCandidate(
        player_key="low", games_remaining=1.0, rates={"pts": 1.0}, stat_basis="projection"
    )
    mid = WaiverCandidate(
        player_key="mid", games_remaining=1.0, rates={"pts": 2.0}, stat_basis="projection"
    )
    high = WaiverCandidate(
        player_key="high", games_remaining=1.0, rates={"pts": 3.0}, stat_basis="projection"
    )

    result = score_waiver_candidates([low, mid, high], frozenset({"pts"}), NO_NEEDS, limit=2)

    assert [r.player_key for r in result] == ["high", "mid"]


def test_tied_scores_break_by_player_key_ascending():
    # identical rates/games -> identical scores; input order is reversed
    # (zzz first) to prove the sort, not insertion order, decides output
    zzz = WaiverCandidate(
        player_key="zzz", games_remaining=1.0, rates={"pts": 1.0}, stat_basis="projection"
    )
    aaa = WaiverCandidate(
        player_key="aaa", games_remaining=1.0, rates={"pts": 1.0}, stat_basis="projection"
    )

    result = score_waiver_candidates([zzz, aaa], frozenset({"pts"}), NO_NEEDS)

    assert [r.player_key for r in result] == ["aaa", "zzz"]


# --- reason token: season-average fallback -------------------------------------


def test_season_average_fallback_reason_token_present_only_when_flagged():
    projected = WaiverCandidate(
        player_key="projected", games_remaining=1.0, rates={"pts": 1.0}, stat_basis="projection"
    )
    fallback = WaiverCandidate(
        player_key="fallback",
        games_remaining=1.0,
        rates={"pts": 1.0},
        stat_basis="season_average",
    )

    result = score_waiver_candidates([projected, fallback], frozenset({"pts"}), NO_NEEDS)
    by_key = {r.player_key: r for r in result}

    assert "season_average_fallback" not in by_key["projected"].reasons
    assert "season_average_fallback" in by_key["fallback"].reasons
    assert by_key["fallback"].stat_basis == "season_average"


# --- categories_helped is always in canonical CATEGORIES order ----------------


def test_categories_helped_uses_canonical_categories_order():
    # candidate helps blk, pts, and ast (all close, all positive rate); rates
    # dict insertion order is deliberately NOT canonical order, to prove the
    # output order comes from CATEGORIES, not dict/insertion order
    candidate = WaiverCandidate(
        player_key="multi",
        games_remaining=1.0,
        rates={"blk": 1.0, "ast": 1.0, "pts": 1.0},
        stat_basis="projection",
    )

    result = score_waiver_candidates(
        [candidate], frozenset({"pts", "ast", "blk"}), NO_NEEDS
    )

    assert result[0].categories_helped == ("pts", "ast", "blk")


# --- fan-plausibility (mandatory) ----------------------------------------------


def test_shot_blocking_big_beats_high_assist_guard_when_blocks_and_turnovers_are_close():
    # M13: the original version of this test only exercised blk, so it would
    # still pass even with the tov sign removed entirely (tov never entered
    # the score). close_categories now includes BOTH blk and tov, tuned so
    # the turnover cost is load-bearing in deciding the winner -- flipping
    # signed_contribution's tov sign flips which player ranks first (see the
    # "if the scoring logic were wrong" comment below), which is exactly
    # what a mandatory plausibility test must catch.
    #
    # close_categories={"blk", "tov"}, no roster needs -> weight[blk] =
    # weight[tov] = 1.0, every other category weight 0 (a guard's huge
    # assist/points numbers earn nothing here). CATEGORY_SCALE: blk=0.5,
    # tov=1.5.
    #   big:   blk(0.6/0.5=1.2)*3 + tov(-(0.3/1.5))*3 = 3.6 - 0.6 = 3.0
    #   guard: blk(0.5/0.5=1.0)*3 + tov(-(1.0/1.5))*3 = 3.0 - 2.0 = 1.0
    # 3.0 > 1.0 -- the shot-blocking, ball-secure big is the right add for a
    # blocks-and-turnovers-close matchup, even though blk alone is close
    # between them (1.2 vs 1.0) and it's the tov gap that decides it.
    #
    # If the scoring logic had tov's sign backwards (a real bug this module
    # shipped with once already, see engine.contribution module docstring),
    # the ranking would flip: big_bugged = 3.6 + 0.6 = 4.2, guard_bugged =
    # 3.0 + 2.0 = 5.0 -> guard would incorrectly win.
    guard = WaiverCandidate(
        player_key="high_assist_guard",
        games_remaining=3.0,
        rates={"ast": 8.0, "pts": 20.0, "blk": 0.5, "tov": 1.0},
        stat_basis="projection",
    )
    big = WaiverCandidate(
        player_key="shot_blocking_big",
        games_remaining=3.0,
        rates={"blk": 0.6, "tov": 0.3, "pts": 10.0, "reb": 8.0},
        stat_basis="projection",
    )

    result = score_waiver_candidates([guard, big], frozenset({"blk", "tov"}), NO_NEEDS)

    assert result[0].player_key == "shot_blocking_big"
    assert result[0].score == pytest.approx(3.0, abs=TOL)
    assert result[1].player_key == "high_assist_guard"
    assert result[1].score == pytest.approx(1.0, abs=TOL)
    assert result[0].categories_helped == ("blk", "tov")


# --- determinism -----------------------------------------------------------


def test_identical_inputs_give_identical_ordering():
    candidates = [
        WaiverCandidate(
            player_key="a", games_remaining=2.0, rates={"pts": 1.0, "reb": 0.5}, stat_basis="projection"
        ),
        WaiverCandidate(
            player_key="b", games_remaining=3.0, rates={"pts": 0.5, "reb": 1.0}, stat_basis="projection"
        ),
        WaiverCandidate(
            player_key="c", games_remaining=1.0, rates={"pts": 2.0, "reb": 2.0}, stat_basis="projection"
        ),
    ]
    close = frozenset({"pts", "reb"})

    first = score_waiver_candidates(candidates, close, NO_NEEDS)
    second = score_waiver_candidates(candidates, close, NO_NEEDS)

    assert first == second


def test_close_category_weight_constant():
    assert CLOSE_CATEGORY_WEIGHT == 1.0
