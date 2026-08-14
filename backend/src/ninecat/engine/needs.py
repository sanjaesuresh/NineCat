"""Per-category "need" weighting: how much a roster's own category z-scores
say it should be favoring that category, on top of raw player value.

No DB access and no dependency on ninecat.models, exactly like zscores.py and
draft.py -- shared by the draft-pick recommender (engine/draft_sim.py) and the
waiver scorer so the two consumers can never drift apart on what counts as a
"need" (see docs/waiver-valuation-plan.md). Extracted unchanged from
draft_sim.py's private _need_weights.
"""

from __future__ import annotations

from ninecat.engine.zscores import CATEGORIES

# roster mean z at/below this is a clear weakness -> weight 0.5.
# boundary is INCLUSIVE (<=), preserved from the original draft_sim.py logic.
NEED_STRONG_Z = -0.35

# roster mean z below this (but above NEED_STRONG_Z) is a mild weakness ->
# weight 0.25; boundary here is EXCLUSIVE (<), also preserved as-is.
NEED_MILD_Z = 0.0


def need_weights(
    roster_zscores: list[dict[str, float]], punt: frozenset[str] = frozenset()
) -> dict[str, float]:
    """Per-category need weight from the roster's mean z: 0.5 for a clear
    weakness, 0.25 for a mild one, 0.0 otherwise. An empty roster has no
    basis for need, so every weight is 0 (falls through to pure value
    ranking downstream). Punted categories are always 0 regardless of roster
    mean -- fixing a punted weakness is not a real need.
    """
    unknown = punt - set(CATEGORIES)
    if unknown:
        raise ValueError(f"unknown punt category: {sorted(unknown)}")
    if not roster_zscores:
        return {cat: 0.0 for cat in CATEGORIES}
    roster_mean = {
        cat: sum(player[cat] for player in roster_zscores) / len(roster_zscores)
        for cat in CATEGORIES
    }
    weights: dict[str, float] = {}
    for cat in CATEGORIES:
        if cat in punt:
            weights[cat] = 0.0
        elif roster_mean[cat] <= NEED_STRONG_Z:
            weights[cat] = 0.5
        elif roster_mean[cat] < NEED_MILD_Z:
            weights[cat] = 0.25
        else:
            weights[cat] = 0.0
    return weights
