import math

import pytest

from ninecat.engine.zscores import PlayerAverages, compute_player_zscores

TOL = 1e-3


# --- main 3-player fixture -------------------------------------------------
#
# FG%: makes 8/7/5, attempts 15/14/12 -> total makes 20, total attempts 41
#   pop_pct = 20/41 = 0.487805
#   impact_i = fgm_i - pop_pct * fga_i
#     A: 8  - 0.487805*15 = 8 - 7.317073 =  0.682927
#     B: 7  - 0.487805*14 = 7 - 6.829268 =  0.170732
#     C: 5  - 0.487805*12 = 5 - 5.853659 = -0.853659
#   mean(impact) = 0 (exact identity: sum(impact) = total_makes - pop_pct*total_attempts = 0)
#   var = (0.682927^2 + 0.170732^2 + 0.853659^2) / 3 = 1.224270 / 3 = 0.408090
#   std = sqrt(0.408090) = 0.638820
#   z_fg: A = 0.682927/0.638820 = 1.069042
#         B = 0.170732/0.638820 = 0.267262
#         C = -0.853659/0.638820 = -1.336301
#
# FT%: A is high-pct/low-volume (3/3 = 100%), B is slightly-lower-pct/high-volume
#      (8/10 = 80%), C is a 50% baseline (5/10) — this is the case that proves
#      volume weighting: B's larger attempt volume must outrank A's higher pct.
#   total makes 3+8+5=16, total attempts 3+10+10=23 -> pop_pct = 16/23 = 0.695652
#   impact_i = ftm_i - pop_pct * fta_i
#     A: 3 - 0.695652*3  = 3 - 2.086957 =  0.913043
#     B: 8 - 0.695652*10 = 8 - 6.956522 =  1.043478
#     C: 5 - 0.695652*10 = 5 - 6.956522 = -1.956522
#   mean = 0, var = (0.913043^2 + 1.043478^2 + 1.956522^2)/3
#        = (0.833648 + 1.088846 + 3.828014)/3 = 5.750508/3 = 1.916836
#   std = sqrt(1.916836) = 1.384498
#   z_ft: A = 0.913043/1.384498 = 0.659534
#         B = 1.043478/1.384498 = 0.753772   <- B beats A despite lower pct
#         C = -1.956522/1.384498 = -1.413073
#
# PTS (plain counting z): 22, 25, 15
#   mean = 62/3 = 20.666667
#   var = (1.333333^2 + 4.333333^2 + (-5.666667)^2)/3 = (1.777778+18.777778+32.111111)/3
#       = 52.666667/3 = 17.555556
#   std = sqrt(17.555556) = 4.189935
#   z_pts: A = 1.333333/4.189935 = 0.318227
#          B = 4.333333/4.189935 = 1.034228
#          C = -5.666667/4.189935 = -1.352455
#
# TOV (counting z then inverted): raw values 1.0, 2.0, 5.0 (C is the high-turnover player)
#   mean = 8/3 = 2.666667
#   var = ((-1.666667)^2 + (-0.666667)^2 + 2.333333^2)/3 = (2.777778+0.444444+5.444444)/3
#       = 8.666667/3 = 2.888889
#   std = sqrt(2.888889) = 1.699673
#   raw z: A = -1.666667/1.699673 = -0.980587
#          B = -0.666667/1.699673 = -0.392235
#          C =  2.333333/1.699673 =  1.372822
#   inverted (stored) tov z: A = 0.980587, B = 0.392235, C = -1.372822
#   -> C (highest raw turnovers) has the most negative tov z, confirming inversion.
PLAYER_A = PlayerAverages(
    player_key="player_a",
    games=70,
    fgm=8,
    fga=15,
    ftm=3,
    fta=3,
    tpm=1,
    pts=22,
    reb=5,
    ast=4,
    stl=1,
    blk=0.5,
    tov=1.0,
)
PLAYER_B = PlayerAverages(
    player_key="player_b",
    games=68,
    fgm=7,
    fga=14,
    ftm=8,
    fta=10,
    tpm=2,
    pts=25,
    reb=8,
    ast=6,
    stl=1.5,
    blk=1.0,
    tov=2.0,
)
PLAYER_C = PlayerAverages(
    player_key="player_c",
    games=75,
    fgm=5,
    fga=12,
    ftm=5,
    fta=10,
    tpm=0.5,
    pts=15,
    reb=10,
    ast=3,
    stl=0.8,
    blk=2.0,
    tov=5.0,
)
MAIN_POPULATION = [PLAYER_A, PLAYER_B, PLAYER_C]


def test_fg_pct_zscores_match_hand_calculation():
    z = compute_player_zscores(MAIN_POPULATION)
    assert z["player_a"]["fg_pct"] == pytest.approx(1.069042, abs=TOL)
    assert z["player_b"]["fg_pct"] == pytest.approx(0.267262, abs=TOL)
    assert z["player_c"]["fg_pct"] == pytest.approx(-1.336301, abs=TOL)


def test_ft_pct_zscores_match_hand_calculation():
    z = compute_player_zscores(MAIN_POPULATION)
    assert z["player_a"]["ft_pct"] == pytest.approx(0.659534, abs=TOL)
    assert z["player_b"]["ft_pct"] == pytest.approx(0.753772, abs=TOL)
    assert z["player_c"]["ft_pct"] == pytest.approx(-1.413073, abs=TOL)


def test_ft_pct_volume_weighting_beats_raw_percentage():
    # player_a shoots 100% on 3 attempts; player_b shoots 80% on 10 attempts.
    # the volume-weighted method must rank b above a, despite a's higher pct.
    z = compute_player_zscores(MAIN_POPULATION)
    assert PLAYER_A.ftm / PLAYER_A.fta > PLAYER_B.ftm / PLAYER_B.fta
    assert z["player_b"]["ft_pct"] > z["player_a"]["ft_pct"]


def test_pts_zscores_match_hand_calculation():
    z = compute_player_zscores(MAIN_POPULATION)
    assert z["player_a"]["pts"] == pytest.approx(0.318227, abs=TOL)
    assert z["player_b"]["pts"] == pytest.approx(1.034228, abs=TOL)
    assert z["player_c"]["pts"] == pytest.approx(-1.352455, abs=TOL)


def test_tov_zscore_is_inverted_so_high_turnovers_are_negative():
    z = compute_player_zscores(MAIN_POPULATION)
    assert z["player_a"]["tov"] == pytest.approx(0.980587, abs=TOL)
    assert z["player_b"]["tov"] == pytest.approx(0.392235, abs=TOL)
    assert z["player_c"]["tov"] == pytest.approx(-1.372822, abs=TOL)
    # player_c has the most turnovers (5.0/game) of the three -> must be the
    # most negative tov z, since positive z always means "good" for every cat
    assert z["player_c"]["tov"] < z["player_b"]["tov"] < z["player_a"]["tov"]


def test_all_nine_category_keys_present_and_finite():
    z = compute_player_zscores(MAIN_POPULATION)
    expected_keys = {
        "fg_pct", "ft_pct", "tpm", "pts", "reb", "ast", "stl", "blk", "tov",
    }
    for player_key in ("player_a", "player_b", "player_c"):
        assert set(z[player_key].keys()) == expected_keys
        for value in z[player_key].values():
            assert isinstance(value, float)
            assert value == value  # not NaN


# --- zero-attempts guard ----------------------------------------------------
#
# player_zero never attempts a free throw (0/0). Its impact must be forced to
# 0 rather than raising ZeroDivisionError or producing NaN from a 0/0 pct.
# The other two players give the population a nonzero FT% spread so the
# zero-attempts guard is exercised independently of the zero-std guard below.
#
# FT%: makes 0, 5, 9; attempts 0, 10, 10 -> pop_pct = 14/20 = 0.7
#   impact_zero = 0 (guarded)
#   impact_p2 = 5 - 0.7*10 = -2.0
#   impact_p3 = 9 - 0.7*10 =  2.0
#   mean = 0, var = (0^2 + (-2)^2 + 2^2)/3 = 8/3 = 2.666667, std = 1.632993
#   z_ft: zero = 0/1.632993 = 0.0
#         p2   = -2/1.632993 = -1.224745
#         p3   =  2/1.632993 =  1.224745
def test_zero_attempts_guards_division_by_zero():
    player_zero = PlayerAverages(
        player_key="zero_fta",
        games=10,
        fgm=2,
        fga=5,
        ftm=0,
        fta=0,
        tpm=0,
        pts=10,
        reb=3,
        ast=2,
        stl=0.5,
        blk=0.5,
        tov=1.0,
    )
    player_2 = PlayerAverages(
        player_key="p2",
        games=10,
        fgm=5,
        fga=10,
        ftm=5,
        fta=10,
        tpm=1,
        pts=15,
        reb=4,
        ast=3,
        stl=0.5,
        blk=0.5,
        tov=1.5,
    )
    player_3 = PlayerAverages(
        player_key="p3",
        games=10,
        fgm=5,
        fga=10,
        ftm=9,
        fta=10,
        tpm=1,
        pts=15,
        reb=4,
        ast=3,
        stl=0.5,
        blk=0.5,
        tov=1.5,
    )

    z = compute_player_zscores([player_zero, player_2, player_3])

    assert z["zero_fta"]["ft_pct"] == pytest.approx(0.0, abs=TOL)
    assert z["p2"]["ft_pct"] == pytest.approx(-1.224745, abs=TOL)
    assert z["p3"]["ft_pct"] == pytest.approx(1.224745, abs=TOL)


# --- zero-variance guard -----------------------------------------------------
def test_zero_variance_population_gives_zero_zscores_everywhere():
    # three identical players: every category (counting and pct-impact alike)
    # has zero spread, so std is 0 for all of them. Division by that std must
    # be guarded to return 0.0 rather than raising or producing NaN/inf.
    identical = PlayerAverages(
        player_key="p",
        games=50,
        fgm=5,
        fga=10,
        ftm=4,
        fta=5,
        tpm=1,
        pts=20,
        reb=6,
        ast=4,
        stl=1,
        blk=1,
        tov=2,
    )
    players = [
        PlayerAverages(**{**identical.__dict__, "player_key": f"p{i}"}) for i in range(3)
    ]

    z = compute_player_zscores(players)

    for player_key in ("p0", "p1", "p2"):
        for category, value in z[player_key].items():
            assert value == pytest.approx(0.0, abs=TOL), (player_key, category, value)


def test_empty_population_returns_empty_dict():
    assert compute_player_zscores([]) == {}


def test_guard_and_negation_paths_never_return_negative_zero():
    # -0.0 == 0.0 is True in Python, so a plain equality/approx assertion can't
    # catch a sign leak; math.copysign(1.0, x) returns -1.0 for -0.0 and +1.0
    # for +0.0, so it's the only reliable way to distinguish them here. This
    # matters because Task 13 serializes these values to JSON, where "-0.0"
    # vs "0.0" is a visible (and confusing) difference to a frontend consumer.

    # zero-attempts guard: (0.0 - pop_pct) * 0 is negative * positive-zero in
    # IEEE754, which yields -0.0 unless explicitly special-cased. Attempts/makes
    # here are chosen as dyadic fractions (halves/quarters) so pop_pct (0.5) and
    # every intermediate sum is EXACT in binary float -- no floating-point noise
    # to obscure the sign, unlike e.g. a 0.7 pop_pct which isn't exactly
    # representable and would make a copysign assertion flaky.
    player_zero = PlayerAverages(
        player_key="zero_fta", games=10, fgm=2, fga=5, ftm=0, fta=0,
        tpm=0, pts=10, reb=3, ast=2, stl=0.5, blk=0.5, tov=1.0,
    )
    player_2 = PlayerAverages(
        player_key="p2", games=10, fgm=5, fga=10, ftm=6, fta=8,
        tpm=1, pts=15, reb=4, ast=3, stl=0.5, blk=0.5, tov=1.5,
    )
    player_3 = PlayerAverages(
        player_key="p3", games=10, fgm=5, fga=10, ftm=2, fta=8,
        tpm=1, pts=15, reb=4, ast=3, stl=0.5, blk=0.5, tov=1.5,
    )
    # pop_pct = (0+6+2)/(0+8+8) = 8/16 = 0.5 exactly; impact_p2 = 6-0.5*8 = 2.0,
    # impact_p3 = 2-0.5*8 = -2.0, impact_zero = 0.0 (guarded) -> mean is exactly
    # 0.0, so zero_fta's z is exactly 0.0/std with no rounding to mask the sign
    z = compute_player_zscores([player_zero, player_2, player_3])
    assert z["zero_fta"]["ft_pct"] == 0.0
    assert math.copysign(1.0, z["zero_fta"]["ft_pct"]) == 1.0

    # zero-variance guard: identical players -> std 0 -> the guard's literal
    # [0.0, ...] list must stay positive-signed
    identical = PlayerAverages(
        player_key="p", games=50, fgm=5, fga=10, ftm=4, fta=5,
        tpm=1, pts=20, reb=6, ast=4, stl=1, blk=1, tov=2,
    )
    same_players = [
        PlayerAverages(**{**identical.__dict__, "player_key": f"same{i}"}) for i in range(3)
    ]
    z_same = compute_player_zscores(same_players)
    assert math.copysign(1.0, z_same["same0"]["reb"]) == 1.0

    # tov negation: a player sitting exactly at the population mean has a raw
    # counting z of 0.0; negating that naively (-0.0) would leak the inversion
    # comment's sign flip into a spurious -0.0 for an at-the-mean player
    # tov values 2.0/4.0/6.0 -> mean 4.0 -> p_mid's raw z is exactly 0.0
    p_low = PlayerAverages(
        player_key="p_low", games=10, fgm=5, fga=10, ftm=5, fta=10,
        tpm=1, pts=15, reb=4, ast=3, stl=0.5, blk=0.5, tov=2.0,
    )
    p_mid = PlayerAverages(
        player_key="p_mid", games=10, fgm=5, fga=10, ftm=5, fta=10,
        tpm=1, pts=15, reb=4, ast=3, stl=0.5, blk=0.5, tov=4.0,
    )
    p_high = PlayerAverages(
        player_key="p_high", games=10, fgm=5, fga=10, ftm=5, fta=10,
        tpm=1, pts=15, reb=4, ast=3, stl=0.5, blk=0.5, tov=6.0,
    )
    z_tov = compute_player_zscores([p_low, p_mid, p_high])
    assert z_tov["p_mid"]["tov"] == pytest.approx(0.0, abs=TOL)
    assert math.copysign(1.0, z_tov["p_mid"]["tov"]) == 1.0
