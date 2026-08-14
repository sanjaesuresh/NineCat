import pytest

from ninecat.engine.weekly import WeeklyPlayerRate, project_week

TOL = 1e-3


# --- counting categories scale linearly with games --------------------------
#
# player_a plays 3 games this week, player_b plays 4.
#   pts:  10*3 + 20*4 = 30 + 80  = 110
#   reb:   5*3 +  8*4 = 15 + 32  = 47
#   ast:   3*3 +  6*4 =  9 + 24  = 33
#   stl:   1*3 +  2*4 =  3 +  8  = 11
#   blk:  0.5*3+  1*4 = 1.5+  4  = 5.5
#   tov:   2*3 +  3*4 =  6 + 12  = 18
#   tpm:   1*3 +  2*4 =  3 +  8  = 11
#   fgm total = 4*3 + 6*4 = 12 + 24 = 36
#   fga total = 8*3 + 12*4 = 24 + 48 = 72  -> fg_pct = 36/72 = 0.5
#   ftm total = 2*3 + 4*4 = 6 + 16 = 22
#   fta total = 2*3 + 5*4 = 6 + 20 = 26   -> ft_pct = 22/26 = 0.846154
#   games total = 3 + 4 = 7
PLAYER_A = WeeklyPlayerRate(
    player_key="player_a",
    games=3,
    fgm=4,
    fga=8,
    ftm=2,
    fta=2,
    tpm=1,
    pts=10,
    reb=5,
    ast=3,
    stl=1,
    blk=0.5,
    tov=2,
)
PLAYER_B = WeeklyPlayerRate(
    player_key="player_b",
    games=4,
    fgm=6,
    fga=12,
    ftm=4,
    fta=5,
    tpm=2,
    pts=20,
    reb=8,
    ast=6,
    stl=2,
    blk=1,
    tov=3,
)


def test_counting_categories_scale_linearly_with_games():
    result = project_week([PLAYER_A, PLAYER_B])
    assert result.totals["pts"] == pytest.approx(110, abs=TOL)
    assert result.totals["reb"] == pytest.approx(47, abs=TOL)
    assert result.totals["ast"] == pytest.approx(33, abs=TOL)
    assert result.totals["stl"] == pytest.approx(11, abs=TOL)
    assert result.totals["blk"] == pytest.approx(5.5, abs=TOL)
    assert result.totals["tov"] == pytest.approx(18, abs=TOL)
    assert result.totals["tpm"] == pytest.approx(11, abs=TOL)


def test_percentages_and_games_and_player_games_match_hand_calculation():
    result = project_week([PLAYER_A, PLAYER_B])
    assert result.totals["fg_pct"] == pytest.approx(0.5, abs=TOL)
    assert result.totals["ft_pct"] == pytest.approx(0.846154, abs=TOL)
    assert result.components == {"fgm": 36, "fga": 72, "ftm": 22, "fta": 26}
    assert result.games == pytest.approx(7, abs=TOL)
    assert result.player_games == {"player_a": 3, "player_b": 4}


# --- percentage weighting: the test that proves the whole module -----------
#
# high-volume 50% shooter (20 attempts, 10 makes) vs low-volume 100% shooter
# (2 attempts, 2 makes), each for a single game this week.
#   combined makes = 10 + 2 = 12, combined attempts = 20 + 2 = 22
#   combined pct   = 12/22 = 0.545455
#   naive average of the two per-player pcts = (0.5 + 1.0)/2 = 0.75
# 0.545455 is much closer to the high-volume shooter's 0.5 than to the naive
# average of 0.75 -- proving attempts are weighted, not per-player pcts averaged.
def test_percentage_weighting_favors_high_volume_over_naive_average():
    high_volume = WeeklyPlayerRate(
        player_key="high_volume",
        games=1,
        fgm=10,
        fga=20,
        ftm=0,
        fta=0,
        tpm=0,
        pts=20,
        reb=5,
        ast=2,
        stl=1,
        blk=0.5,
        tov=2,
    )
    low_volume = WeeklyPlayerRate(
        player_key="low_volume",
        games=1,
        fgm=2,
        fga=2,
        ftm=0,
        fta=0,
        tpm=0,
        pts=4,
        reb=1,
        ast=0,
        stl=0,
        blk=0,
        tov=0,
    )

    result = project_week([high_volume, low_volume])

    naive_average = (10 / 20 + 2 / 2) / 2  # = 0.75
    assert result.totals["fg_pct"] == pytest.approx(0.545455, abs=TOL)
    assert result.totals["fg_pct"] != pytest.approx(naive_average, abs=TOL)
    # nearer the high-volume shooter's 0.5 than the naive average's 0.75
    assert abs(result.totals["fg_pct"] - 0.5) < abs(result.totals["fg_pct"] - naive_average)


# --- zero attempts guard -----------------------------------------------------
def test_zero_attempts_gives_zero_pct_not_zero_division_error():
    no_shots = WeeklyPlayerRate(
        player_key="no_shots",
        games=2,
        fgm=0,
        fga=0,
        ftm=0,
        fta=0,
        tpm=0,
        pts=0,
        reb=3,
        ast=1,
        stl=0.5,
        blk=0.5,
        tov=1,
    )
    result = project_week([no_shots])
    assert result.totals["fg_pct"] == 0.0
    assert result.totals["ft_pct"] == 0.0


# --- empty roster / zero-games player / negative games ---------------------
def test_empty_roster_returns_zeroed_projection_not_an_exception():
    result = project_week([])
    for category in (
        "fg_pct", "ft_pct", "tpm", "pts", "reb", "ast", "stl", "blk", "tov",
    ):
        assert result.totals[category] == 0.0
    assert result.components == {"fgm": 0.0, "fga": 0.0, "ftm": 0.0, "fta": 0.0}
    assert result.games == 0.0
    assert result.player_games == {}


def test_zero_games_player_contributes_nothing_but_still_appears():
    benched = WeeklyPlayerRate(
        player_key="benched",
        games=0,
        fgm=5,
        fga=10,
        ftm=4,
        fta=5,
        tpm=2,
        pts=20,
        reb=6,
        ast=4,
        stl=1,
        blk=1,
        tov=2,
    )
    result = project_week([benched, PLAYER_A])
    # benched's rates never get multiplied by any games -> same totals as
    # player_a alone would produce
    assert result.totals["pts"] == pytest.approx(PLAYER_A.pts * PLAYER_A.games, abs=TOL)
    assert result.player_games == {"benched": 0.0, "player_a": 3}


def test_negative_games_raises_value_error_naming_the_player():
    injured = WeeklyPlayerRate(
        player_key="injured_guy",
        games=-1,
        fgm=5,
        fga=10,
        ftm=4,
        fta=5,
        tpm=2,
        pts=20,
        reb=6,
        ast=4,
        stl=1,
        blk=1,
        tov=2,
    )
    with pytest.raises(ValueError, match="injured_guy"):
        project_week([injured])


# --- fan plausibility --------------------------------------------------------
#
# a roster of high-usage guards must project more assists than a roster of
# centers, and the centers must project more blocks and rebounds -- realistic
# per-game lines. Games-this-week deliberately DIFFER, both across rosters and
# per player within a roster (real fantasy rosters mix players from different
# NBA teams, whose weekly schedules differ).
#
# WEEKLY M1: with all six players at an identical games=4, the games
# multiplier was a single shared scalar cancelling out of every comparison,
# so a mutation dropping it entirely passed unnoticed. Giving players
# DIFFERENT per-player games turned out NOT to be sufficient on its own,
# confirmed by actually applying the mutations (see task notes): every
# guard's per-player ast rate already exceeds every center's, and every
# center's per-player reb/blk/fg_pct rate already exceeds every guard's, so
# ANY nonnegative reweighting of those per-player values -- the correct
# games-weighted sum, an unweighted sum, or a naive per-player average --
# preserves the same ">"/"<" direction regardless of which games values are
# chosen. A "roster A's total > roster B's total" assertion can never detect
# a weighting-scheme mutation under those conditions. So this test also pins
# the EXACT hand-computed totals (games-weighted, matching project_week's
# contract) for ast/reb/blk/fg_pct/ft_pct below -- exact equality DOES catch
# both a dropped games multiplier and a naive per-player pct average,
# because either mutation changes the numeric value even when it does not
# flip the sign.
def test_fan_plausibility_guards_assist_more_centers_rebound_and_block_more():
    guards = [
        WeeklyPlayerRate(
            player_key="pg1", games=4, fgm=6, fga=13, ftm=3, fta=3.5,
            tpm=2, pts=17, reb=4, ast=8, stl=1.5, blk=0.3, tov=3,
        ),
        WeeklyPlayerRate(
            player_key="pg2", games=3, fgm=5, fga=11, ftm=2, fta=2.5,
            tpm=1.5, pts=13, reb=3, ast=6, stl=1, blk=0.2, tov=2,
        ),
        WeeklyPlayerRate(
            player_key="pg3", games=4, fgm=7, fga=15, ftm=4, fta=5,
            tpm=2.5, pts=20, reb=5, ast=9, stl=1.8, blk=0.1, tov=3.5,
        ),
    ]
    centers = [
        WeeklyPlayerRate(
            player_key="c1", games=3, fgm=7, fga=12, ftm=3, fta=5,
            tpm=0, pts=17, reb=11, ast=2, stl=0.7, blk=2.2, tov=2,
        ),
        WeeklyPlayerRate(
            player_key="c2", games=4, fgm=6, fga=10, ftm=2, fta=3,
            tpm=0, pts=14, reb=9, ast=1.5, stl=0.5, blk=1.8, tov=1.5,
        ),
        WeeklyPlayerRate(
            player_key="c3", games=3, fgm=8, fga=13, ftm=4, fta=6,
            tpm=0.1, pts=20, reb=12, ast=1, stl=0.6, blk=2.5, tov=2.2,
        ),
    ]

    guard_totals = project_week(guards).totals
    center_totals = project_week(centers).totals

    assert guard_totals["ast"] > center_totals["ast"]
    assert center_totals["blk"] > guard_totals["blk"]
    assert center_totals["reb"] > guard_totals["reb"]
    # bigs shoot a higher field-goal % (closer to the rim); guards, being
    # more frequently fouled on drives and better touch shooters, shoot a
    # higher free-throw % -- the reverse of the fg_pct read.
    assert center_totals["fg_pct"] > guard_totals["fg_pct"]
    assert guard_totals["ft_pct"] > center_totals["ft_pct"]

    # exact hand-computed totals (games-weighted: e.g. guard ast =
    # 8*4 + 6*3 + 9*4 = 86; center fg_pct = (7*3+6*4+8*3)/(12*3+10*4+13*3) =
    # 69/115 = 0.6) -- these are the assertions that are actually sensitive
    # to HOW games/attempts are weighted, per the docstring above.
    assert guard_totals["ast"] == pytest.approx(86.0, abs=TOL)
    assert center_totals["ast"] == pytest.approx(15.0, abs=TOL)
    assert guard_totals["reb"] == pytest.approx(45.0, abs=TOL)
    assert center_totals["reb"] == pytest.approx(105.0, abs=TOL)
    assert guard_totals["blk"] == pytest.approx(2.2, abs=TOL)
    assert center_totals["blk"] == pytest.approx(21.3, abs=TOL)
    assert guard_totals["fg_pct"] == pytest.approx(0.462069, abs=TOL)
    assert center_totals["fg_pct"] == pytest.approx(0.6, abs=TOL)
    assert guard_totals["ft_pct"] == pytest.approx(0.819277, abs=TOL)
    assert center_totals["ft_pct"] == pytest.approx(0.644444, abs=TOL)


# --- determinism -------------------------------------------------------------
def test_deterministic_same_input_gives_equal_results():
    players = [PLAYER_A, PLAYER_B]
    first = project_week(players)
    second = project_week(players)
    assert first == second
