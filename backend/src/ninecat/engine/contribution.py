"""Shared scoring primitives for the two "which free agent helps me this
week" scorers: engine.streaming (day/budget assignment) and engine.waivers
(ranking/presentation). Both modules independently answer the same question
-- which free agent helps THIS roster THIS week -- and had started to
disagree with each other on the basic rules. This module is now the single
place those rules live, so streaming and waivers can never drift apart
again; streaming owns only WHEN to add someone, waivers owns only HOW to
present the ranked list, and both get "is this any good at all" from here.

No DB access and no dependency on ninecat.models, same as zscores.py.

This module owns four rules:

1. THE SIGN RULE. Turnovers are a cost, not a benefit: in weekly 9-cat they
   accumulate, so playing more games can only ever ADD turnovers, never
   subtract them. Every other category's raw per-game rate IS its
   contribution as-is. See signed_contribution. (Deliberately asymmetric
   with engine.zscores, which pre-inverts tov before handing it to callers --
   the raw per-game rate shape these two modules receive is not pre-inverted,
   so they must apply the sign themselves; see either module's docstring for
   why that responsibility lives here rather than in every future caller.)

2. PER-CATEGORY SCALING. Both modules used to sum RAW per-game rates across
   categories, so a category's numeric SIZE decided how much it counted
   toward a candidate's score, not how much it actually mattered to a close
   matchup -- a 22-pts/0.4-stl scorer beat a 6-pts/2.5-stl specialist on a
   points-and-steals-close matchup purely because points is a numerically
   bigger stat, even though the specialist is the actually correct pick.
   scaled_contribution divides each category's signed contribution by
   CATEGORY_SCALE[cat], a fixed reference "typical productive per-game rate"
   for that category, turning a contribution into "how many typical
   performances is this" -- comparable across categories the same way a
   z-score is. LIMITATION: unlike engine.zscores (which computes a real
   population standard deviation), CATEGORY_SCALE is a fixed, hand-chosen
   constant. It does not adapt to league size, punt-heavy formats, or a
   shifting statistical era, and it exists specifically because these two
   modules score a candidate against a fixed close-category set rather than
   against a ranked population the way draft/build-profile z-scores do --
   there usually isn't a population handy to compute a real stdev from (a
   single free agent scored one at a time, or a small ad-hoc candidate
   pool). Treat these numbers as "roughly right", not authoritative.

3. THE WORTH-IT GATE. A candidate whose score (streaming: the best remaining
   (day, candidate) pick; waivers: the candidate's total score) is at or
   below zero is never a recommendation. A candidate contributing nothing,
   or actively hurting the categories they're supposedly targeting (e.g.
   turnover cost outweighing the counting-stat gain), is not a suggestion a
   real manager would want -- no matter how it sorts against worse options.
   See is_worth_it.

4. THE "HELPS X" RULE, tov included. A category counts as genuinely helped
   when its raw rate clears a real bar -- for tov that is a LOW rate
   (< LOW_TOV_RATE), never merely "present" (every real player has some tov
   rate, and a high one is a cost, not a help), and only when the candidate
   actually plays (games_remaining > 0): a player who does not play does not
   help your turnovers, no matter how low their season rate reads. Every
   other category just needs a positive raw rate. See helps_category. This
   used to differ between the two modules -- waivers used the low-rate rule
   below; streaming used "signed contribution is positive", which for a real
   (non-negative) tov rate is never true, so streaming's "category:tov"
   reason token effectively never fired. The low-rate rule is the one
   that's actually useful to a user, so it is the only rule now, in both
   modules, driven by the same UI token ("category:tov").
"""

from __future__ import annotations

TOV_CATEGORY = "tov"

# a candidate's raw tov rate below this (turnovers/game) counts as "helping"
# turnovers -- see module docstring point 4. Shared by both modules so the
# "category:tov" reason token means the same thing everywhere it's emitted.
LOW_TOV_RATE = 1.5

# each category's rough "typical productive per-game rate" for a startable
# fantasy player -- a fixed reference point, NOT derived from any live
# population (see module docstring point 2 for the rationale and the
# limitation). Used only to make one category's contribution comparable in
# size to another's; never surfaced to a user directly.
CATEGORY_SCALE: dict[str, float] = {
    "fg_pct": 0.01,
    "ft_pct": 0.02,
    "tpm": 1.0,
    "pts": 10.0,
    "reb": 4.0,
    "ast": 3.0,
    "stl": 1.0,
    "blk": 0.5,
    "tov": 1.5,
}


def signed_contribution(cat: str, rate: float) -> float:
    """Turnovers subtract from a candidate's contribution; every other
    category's raw rate IS its contribution. Centralized so value/score and
    categories_helped can never drift on which categories are signed which
    way (see module docstring point 1)."""
    return -rate if cat == TOV_CATEGORY else rate


def scaled_contribution(cat: str, rate: float) -> float:
    """signed_contribution divided by the category's fixed scale factor, so
    it is comparable in size to every other category's (see module
    docstring point 2). This is what both streaming's day/budget value and
    waivers' ranking score must sum, never the raw per-game rate."""
    return signed_contribution(cat, rate) / CATEGORY_SCALE[cat]


def helps_category(cat: str, rate: float, games_remaining: float) -> bool:
    """Whether this category is a genuine, presentable "helps X" claim (see
    module docstring point 4). Callers are expected to only ask this for
    categories that already carry real relevance (close, a need, or both,
    depending on the caller) -- this function only judges the rate/games
    side of the question, not whether the category is worth asking about at
    all."""
    if cat == TOV_CATEGORY:
        return rate < LOW_TOV_RATE and games_remaining > 0
    return rate > 0.0


def is_worth_it(score: float) -> bool:
    """A score at or below zero is never a recommendation -- see module
    docstring point 3."""
    return score > 0.0


def category_reason_token(cat: str) -> str:
    """The "category:<key>" reason token both modules emit, one per entry
    in a candidate's categories_helped. Centralized so the literal format
    lives in exactly one place."""
    return f"category:{cat}"
