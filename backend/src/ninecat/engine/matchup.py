"""Pure matchup comparison and verdict math for the NineCat engine.

This module has no DB access and no dependency on ninecat.models — like
zscores.py and weekly.py, it consumes a fixed input contract (weekly.py's
WeeklyProjection) and returns plain dataclasses. It owns the one piece of
domain knowledge weekly.py deliberately leaves out: turnovers invert (lower
is better), so weekly.py's raw projected tov total is not yet "my advantage"
until this module flips it.

Close-margin classification uses TWO different rules depending on category
scale, not one. The seven counting categories (pts, reb, ast, etc.) are
unbounded sums where a proportional threshold makes sense -- a 3-point margin
means something very different in points than in blocks, so CLOSE_MARGIN_RATIO
scales with the combined total. fg_pct/ft_pct are NOT like that: they are
already ratios bounded near [0, 1], so applying the SAME proportional rule to
their combined total (roughly 1.0) collapses to a threshold of ~0.05 -- i.e.
"close" would swallow any gap under ~5 percentage points, and .500 vs .460 (a
real blowout no single streamed add closes) would misclassify as close. That
misclassification would silently poison close_categories/focus, which both
the streaming optimizer and waiver ranking key off. So fg_pct/ft_pct instead
use CLOSE_MARGIN_ABS_PCT, a fixed percentage-point threshold independent of
the combined total.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninecat.engine.weekly import WeeklyProjection
from ninecat.engine.zscores import CATEGORIES

# a counting category is a "close call" when the margin is within this
# fraction of the combined total of both sides -- proportional, not absolute,
# because a fixed unit threshold means something very different in points
# than in blocks. Does NOT apply to fg_pct/ft_pct -- see CLOSE_MARGIN_ABS_PCT.
CLOSE_MARGIN_RATIO = 0.05

# fg_pct/ft_pct are ratio-scale (combined total ~1.0), so CLOSE_MARGIN_RATIO
# would floor "close" at ~5 percentage points of gap -- a real blowout, not a
# streamable margin. 0.0075 (three-quarters of a percentage point) is inside
# the 0.005-0.01 range a single week's worth of streamed FT/FG volume can
# realistically move.
CLOSE_MARGIN_ABS_PCT = 0.0075

# the two categories compared on an absolute percentage-point scale rather
# than proportionally to the combined total -- see module docstring
_RATIO_CATEGORIES = ("fg_pct", "ft_pct")

# the one category where a lower total is the better outcome; every other
# category in CATEGORIES is "higher is better"
_LOWER_IS_BETTER = ("tov",)


@dataclass(frozen=True)
class CategoryVerdict:
    """One category's head-to-head read.

    mine/theirs are the raw projected totals (unoriented, so the UI can show
    real numbers, e.g. actual projected turnovers for each side). margin is
    my advantage in the category (positive = I'm ahead), computed AFTER the
    tov orientation fix, so a positive tov margin always means "winning" like
    every other category. verdict is "winning" / "losing" / "close" / "tie" --
    "tie" is reserved for EXACT equality (margin == 0), distinct from "close"
    (nonzero margin, but small relative to the combined total): a dead-level
    45-45 category should read as a tie to the user, not imply someone's
    narrowly ahead.
    """

    category: str
    mine: float
    theirs: float
    margin: float
    verdict: str


@dataclass(frozen=True)
class MatchupComparison:
    """Full 9-category comparison.

    projected_score tallies categories by whichever side is currently ahead
    (margin != 0); a tied category (margin == 0) counts to neither.
    close_categories/focus surface which categories are still ACTIONABLE
    streaming-optimizer targets -- deliberately a different question from
    verdict's "tie" state (see _classify's docstring for why a 0-0 tie is
    excluded from this list while a nonzero 45-45 tie is included). focus is
    close_categories ranked most-flippable (smallest relative margin) first,
    for the add-schedule optimizer (T6) to target.

    mine_games/their_games carry each side's WeeklyProjection.games total
    through unchanged -- this module used to discard that data-quality signal
    entirely, leaving callers (the API layer, previously) to re-derive their
    own zero-games guard from the raw projections instead of the comparison.
    A zero on either side means every projected total on that side is 0.0
    because no schedule rows exist for the range (unsynced/stale schedule,
    or a real league before its first week's games land), NOT a genuinely
    empty offense -- callers must treat that as missing data, not fact.
    """

    categories: tuple[CategoryVerdict, ...]
    projected_score: tuple[int, int]
    close_categories: tuple[str, ...]
    focus: tuple[str, ...]
    mine_games: float
    their_games: float


def _oriented_margin(category: str, mine: float, theirs: float) -> float:
    """My advantage in this category, positive = I'm ahead. tov is the one
    category where fewer is better, so its subtraction is flipped; every
    other category is a plain mine - theirs.
    """
    if category in _LOWER_IS_BETTER:
        return theirs - mine
    return mine - theirs


def _classify(category: str, margin: float, combined: float) -> str:
    """winning/losing/close/tie from an oriented margin and the category's
    raw combined total (mine + theirs, unoriented magnitudes).

    "tie" is exact equality (margin == 0) -- distinct from "close" (a real,
    if narrow, leader). This covers both a genuine dead-level category (e.g.
    45-45) and the degenerate 0-0 case; both are margin == 0. "close" is only
    reachable with a nonzero margin, at which point combined is guaranteed
    > 0 (margin != 0 implies mine != theirs, and both are non-negative
    totals), so the ratio test below never divides by zero.

    fg_pct/ft_pct use CLOSE_MARGIN_ABS_PCT (an absolute percentage-point gap)
    instead of CLOSE_MARGIN_RATIO * combined -- see module docstring for why
    the proportional rule degenerates on a ratio-scale category.
    """
    if margin == 0:
        return "tie"
    threshold = (
        CLOSE_MARGIN_ABS_PCT if category in _RATIO_CATEGORIES else CLOSE_MARGIN_RATIO * combined
    )
    if abs(margin) <= threshold:
        return "close"
    return "winning" if margin > 0 else "losing"


def compare_matchup(mine: WeeklyProjection, theirs: WeeklyProjection) -> MatchupComparison:
    """Compare two rosters' weekly projections category by category.

    Percentages (fg_pct/ft_pct) are already computed by weekly.py and are
    compared directly here, never recomputed from components -- weekly.py
    owns make/attempt volume weighting, this module only owns comparison.
    """
    category_verdicts = []
    for cat in CATEGORIES:
        my_total = mine.totals[cat]
        their_total = theirs.totals[cat]
        margin = _oriented_margin(cat, my_total, their_total)
        combined = my_total + their_total
        verdict = _classify(cat, margin, combined)
        category_verdicts.append(
            CategoryVerdict(
                category=cat,
                mine=my_total,
                theirs=their_total,
                margin=margin,
                verdict=verdict,
            )
        )

    # projected_score: whoever's ahead wins the category regardless of how
    # close it is; a tied category (margin == 0) counts to neither side
    mine_wins = sum(1 for cv in category_verdicts if cv.margin > 0)
    their_wins = sum(1 for cv in category_verdicts if cv.margin < 0)

    # close_categories/focus answer "what can the streaming optimizer still
    # flip", a different question from verdict's "tie" state:
    #  - verdict == "close": always actionable (a real, nonzero, narrow gap).
    #  - verdict == "tie" AND combined != 0 (e.g. 45-45): dead level and
    #    eminently flippable -- exactly what the optimizer should chase.
    #  - verdict == "tie" AND combined == 0 (0-0): almost always MISSING
    #    DATA (no schedule rows / no games this week for either roster),
    #    not a genuinely level contest. Offering it as the top flip target
    #    would send the optimizer chasing a phantom, so it's excluded even
    #    though it's technically "tied". Do not remove this exclusion.
    close = [
        cv
        for cv in category_verdicts
        if cv.verdict == "close" or (cv.verdict == "tie" and (cv.mine + cv.theirs) != 0)
    ]
    close_categories = tuple(cv.category for cv in close)

    # focus: most flippable first, i.e. smallest relative margin (the same
    # ratio the close test uses) -- ties keep canonical CATEGORIES order
    # because sorted() is stable and `close` was built in that order
    ranked = sorted(close, key=lambda cv: abs(cv.margin) / (cv.mine + cv.theirs))
    focus = tuple(cv.category for cv in ranked)

    return MatchupComparison(
        categories=tuple(category_verdicts),
        projected_score=(mine_wins, their_wins),
        close_categories=close_categories,
        focus=focus,
        mine_games=mine.games,
        their_games=theirs.games,
    )
