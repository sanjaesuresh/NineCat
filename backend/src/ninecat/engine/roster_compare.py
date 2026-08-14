"""Roster comparison: per-category surplus/deficit analysis WITH DEPTH.

A category can be labelled "strong" by build_profile purely because one
elite player carries it -- trading that player doesn't just weaken the
category, it collapses it. This module reuses build_profile's strong/punt
labels (so the two can never disagree) and adds a depth/fragility layer on
top, so a fragile "strong" category is excluded from surplus rather than
offered up as if it were genuinely tradeable.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninecat.engine.build_profile import PUNT_MEAN_Z, STRONG_MEAN_Z, compute_team_profile
from ninecat.engine.zscores import CATEGORIES

# depth counts players whose z in a category clears this bar -- deliberately
# separate from STRONG_MEAN_Z/PUNT_MEAN_Z, which classify the roster as a
# whole rather than an individual player's contribution to it
MEANINGFUL_Z = 0.5

# a "strong" category is fragile once one player supplies this share (or
# more) of its positive z -- trading that player collapses the category
# rather than merely weakening it
FRAGILE_SHARE = 0.5


@dataclass(frozen=True)
class RosterPlayer:
    """One roster player's per-category z-scores, as produced by
    compute_player_zscores (tov already inverted so positive is always good;
    this module never re-inverts it)."""

    player_key: str
    zscores: dict[str, float]


@dataclass(frozen=True)
class CategoryStrength:
    category: str
    total: float
    mean: float
    label: str  # "strong" | "average" | "punt" -- build_profile's vocabulary
    depth: int
    fragile: bool
    top_contributor: str | None
    top_share: float


@dataclass(frozen=True)
class RosterComparison:
    mine: dict[str, CategoryStrength]
    theirs: dict[str, CategoryStrength]
    my_surplus: tuple[str, ...]
    my_deficit: tuple[str, ...]
    their_surplus: tuple[str, ...]
    their_deficit: tuple[str, ...]


def _validate_roster(roster: list[RosterPlayer]) -> None:
    for player in roster:
        missing = [cat for cat in CATEGORIES if cat not in player.zscores]
        if missing:
            raise ValueError(
                f"player {player.player_key!r} missing z-scores for categories: {missing}"
            )


def _category_strength(
    roster: list[RosterPlayer], category: str, label: str, total: float
) -> CategoryStrength:
    roster_size = len(roster)
    # same formula build_profile uses internally to derive its label, exposed
    # here so callers get the mean the label was actually decided on
    mean = (total / roster_size) if roster_size else 0.0

    depth = sum(1 for p in roster if p.zscores[category] >= MEANINGFUL_Z)

    # negatives excluded from the concentration measure: a bad rebounder
    # doesn't make good rebounding look MORE concentrated than it is
    positive = [(p.player_key, p.zscores[category]) for p in roster if p.zscores[category] > 0]
    if positive:
        positive_sum = sum(z for _, z in positive)
        # tie-break by player_key for determinism when two players share the max z
        top_key, top_z = min(positive, key=lambda kv: (-kv[1], kv[0]))
        top_share = (top_z / positive_sum) if positive_sum > 0 else 0.0
    else:
        top_key, top_share = None, 0.0

    # a one-man (or one-man-dominated) "strong" category is the exact trap
    # this module exists to catch: it reads as tradeable surplus but trading
    # that player collapses the category rather than just softening it
    fragile = label == "strong" and (depth <= 1 or top_share >= FRAGILE_SHARE)

    return CategoryStrength(
        category=category,
        total=total,
        mean=mean,
        label=label,
        depth=depth,
        fragile=fragile,
        top_contributor=top_key,
        top_share=top_share,
    )


def _strengths(roster: list[RosterPlayer]) -> dict[str, CategoryStrength]:
    profile = compute_team_profile([dict(p.zscores) for p in roster])
    return {
        cat: _category_strength(roster, cat, profile["labels"][cat], profile["totals"][cat])
        for cat in CATEGORIES
    }


def compare_rosters(mine: list[RosterPlayer], theirs: list[RosterPlayer]) -> RosterComparison:
    """Classify both rosters' per-category strength (with depth/fragility)
    and derive surplus/deficit category tuples for each side. Surplus is
    "strong" minus fragile strengths -- the whole point of this module is
    that a fragile strength is never offered as surplus. Deficit is "punt".
    """
    _validate_roster(mine)
    _validate_roster(theirs)

    mine_strengths = _strengths(mine)
    theirs_strengths = _strengths(theirs)

    my_surplus = tuple(
        cat for cat in CATEGORIES if mine_strengths[cat].label == "strong" and not mine_strengths[cat].fragile
    )
    my_deficit = tuple(cat for cat in CATEGORIES if mine_strengths[cat].label == "punt")
    their_surplus = tuple(
        cat
        for cat in CATEGORIES
        if theirs_strengths[cat].label == "strong" and not theirs_strengths[cat].fragile
    )
    their_deficit = tuple(cat for cat in CATEGORIES if theirs_strengths[cat].label == "punt")

    return RosterComparison(
        mine=mine_strengths,
        theirs=theirs_strengths,
        my_surplus=my_surplus,
        my_deficit=my_deficit,
        their_surplus=their_surplus,
        their_deficit=their_deficit,
    )
