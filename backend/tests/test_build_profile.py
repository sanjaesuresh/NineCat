import pytest

from ninecat.engine.build_profile import PUNT_MEAN_Z, STRONG_MEAN_Z, compute_team_profile

TOL = 1e-9


def _zero_cats(**overrides):
    # helper: a full 9-cat z dict defaulting every category to 0.0, with only
    # the categories under test overridden — keeps each fixture focused
    base = {
        "fg_pct": 0.0,
        "ft_pct": 0.0,
        "tpm": 0.0,
        "pts": 0.0,
        "reb": 0.0,
        "ast": 0.0,
        "stl": 0.0,
        "blk": 0.0,
        "tov": 0.0,
    }
    base.update(overrides)
    return base


def test_rebound_stacked_roster_is_strong_and_low_assist_roster_is_punt():
    # a roster of three bigs: strong rebounding (reb mean well past +0.35) and
    # near-zero assists per game, so their assist z-scores are all strongly
    # negative (mean well past -0.35) -> punt. fg_pct stays near 0 (average).
    roster = [
        _zero_cats(fg_pct=0.1, reb=1.0, ast=-0.5),
        _zero_cats(fg_pct=-0.1, reb=1.2, ast=-0.3),
        _zero_cats(fg_pct=0.0, reb=1.0, ast=-1.5),
    ]

    profile = compute_team_profile(roster)

    # totals: reb = 1.0+1.2+1.0 = 3.2; ast = -0.5-0.3-1.5 = -2.3; fg_pct = 0.0
    assert profile["totals"]["reb"] == pytest.approx(3.2, abs=TOL)
    assert profile["totals"]["ast"] == pytest.approx(-2.3, abs=TOL)
    assert profile["totals"]["fg_pct"] == pytest.approx(0.0, abs=TOL)

    # means: reb = 3.2/3 = 1.0667 (>= 0.35 -> strong); ast = -2.3/3 = -0.7667
    # (<= -0.35 -> punt); fg_pct = 0.0/3 = 0.0 -> average
    assert profile["labels"]["reb"] == "strong"
    assert profile["labels"]["ast"] == "punt"
    assert profile["labels"]["fg_pct"] == "average"
    # untouched categories stay at 0.0 total/mean -> average
    assert profile["labels"]["pts"] == "average"


def test_thirteen_player_roster_discriminates_by_mean_not_sum():
    # regression for the sum-threshold bug: under the old sum >= 2.0 rule, a
    # modest +0.3 z per player across a realistic 13-player roster sums to
    # 3.9 -- comfortably past the old threshold for basically every category,
    # making the label useless (everything "strong" on any decent roster).
    # Mean-based labeling fixes this: a 0.3 mean stays "average" (below
    # STRONG_MEAN_Z), while a genuinely stronger category (0.4 mean) still
    # clears it, and a clearly weak category (-0.5 mean) still reads "punt".
    player_cats = _zero_cats(
        fg_pct=0.3,
        ft_pct=0.3,
        tpm=0.3,
        pts=0.3,
        reb=0.4,
        ast=0.1,
        stl=0.3,
        blk=0.3,
        tov=-0.5,
    )
    roster = [dict(player_cats) for _ in range(13)]

    profile = compute_team_profile(roster)

    # totals: 13 * per-player value (identical roster) -> reb 5.2, tov -6.5
    assert profile["totals"]["reb"] == pytest.approx(5.2, abs=TOL)
    assert profile["totals"]["tov"] == pytest.approx(-6.5, abs=TOL)

    # means: reb 0.4 (>= 0.35 -> strong); tov -0.5 (<= -0.35 -> punt);
    # ast 0.1 (middling, between the thresholds -> average)
    assert profile["labels"]["reb"] == "strong"
    assert profile["labels"]["tov"] == "punt"
    assert profile["labels"]["ast"] == "average"
    # the regression check itself: widespread-but-modest z (0.3 mean, 3.9 sum)
    # must NOT be "strong" just because 13 players compound the raw sum
    for cat in ("fg_pct", "ft_pct", "tpm", "pts", "stl", "blk"):
        assert profile["labels"][cat] == "average", cat
    assert not all(label == "strong" for label in profile["labels"].values())


def test_threshold_boundaries_are_inclusive():
    # a single-player roster makes the roster mean equal to that player's raw
    # z (total / 1), so we can hit the threshold constants exactly.
    roster = [
        _zero_cats(
            fg_pct=STRONG_MEAN_Z,  # exactly at strong boundary -> strong
            ft_pct=STRONG_MEAN_Z - 0.001,  # just under -> average
            tpm=PUNT_MEAN_Z,  # exactly at punt boundary -> punt
            pts=PUNT_MEAN_Z + 0.001,  # just above -> average
        )
    ]

    profile = compute_team_profile(roster)

    assert profile["labels"]["fg_pct"] == "strong"
    assert profile["labels"]["ft_pct"] == "average"
    assert profile["labels"]["tpm"] == "punt"
    assert profile["labels"]["pts"] == "average"


def test_empty_roster_gives_zero_totals_and_average_labels():
    # documented behavior: an empty roster has no signal to classify, so this
    # returns all-average/all-zero rather than raising (mean_z guarded to 0.0
    # when roster_size is 0, avoiding a ZeroDivisionError)
    profile = compute_team_profile([])
    for category, total in profile["totals"].items():
        assert total == 0.0
    for category, label in profile["labels"].items():
        assert label == "average"
