"""Team build-profile classification: sums a roster's per-category z-scores
and labels each category strong/average/punt.
"""

from __future__ import annotations

from ninecat.engine.zscores import CATEGORIES

# labels are decided on the roster's PER-PLAYER MEAN z (total / roster size),
# not the raw sum. A raw-sum threshold degenerates on real rosters: 13 players
# each contributing a modest +0.3 z already sum to +3.9, which would clear
# almost any sum threshold for nearly every category regardless of whether the
# roster is actually strong there. The mean stays a fixed per-player scale
# that a roster has to genuinely earn, independent of roster size.
# +0.35 mean: a full roster averaging clearly-above-replacement in this cat
STRONG_MEAN_Z = 0.35

# symmetric with STRONG_MEAN_Z: a roster averaging this far below replacement
# in a category is a deliberate (or de facto) punt, not noise
PUNT_MEAN_Z = -0.35


def compute_team_profile(
    roster_zscores: list[dict[str, float]],
) -> dict[str, dict[str, float] | dict[str, str]]:
    """Given a roster's per-player category->z dicts (as produced by
    compute_player_zscores), sum each category across the roster (returned as
    "totals") and label it "strong" / "average" / "punt" (returned as
    "labels") by comparing the roster's per-player MEAN z in that category —
    total / roster size — against the module thresholds. An empty roster has
    no signal to classify, so every category is labeled "average" (not an
    error) with totals of 0.0.
    """
    roster_size = len(roster_zscores)
    totals = {cat: 0.0 for cat in CATEGORIES}
    for player_cats in roster_zscores:
        for cat in CATEGORIES:
            totals[cat] += player_cats[cat]

    labels = {}
    for cat, total in totals.items():
        mean_z = (total / roster_size) if roster_size else 0.0
        if mean_z >= STRONG_MEAN_Z:
            labels[cat] = "strong"
        elif mean_z <= PUNT_MEAN_Z:
            labels[cat] = "punt"
        else:
            labels[cat] = "average"

    return {"totals": totals, "labels": labels}
