"""Composite score, confidence, and model-vs-consensus ranking (Task 13).

Blends the eight upstream components (9-cat value, availability, playoff
window, role/usage, team pace, category scarcity, and consensus) into one
per-player score, renormalizing settings.composite_weights over whichever
components a given player actually has. `model_rank` always excludes the
consensus component so downstream callers can see how much of the final
ranking consensus actually moved. Pure function, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from nineproj.config import Settings
from nineproj.models.availability import Availability
from nineproj.models.roles import AdjustedProjection
from nineproj.models.rookies import RookieFlags
from nineproj.utils.stats import population_zscores
from nineproj.value.consensus import ConsensusResult, Disagreement
from nineproj.value.consensus import disagreement as compute_disagreement
from nineproj.value.ninecat import PlayerValue
from nineproj.value.playoffs import PlayoffValue

# the 8 composite component keys, matching settings.composite_weights' field
# names exactly so CompositeWeights.model_dump() can key straight into them
_COMPONENTS: tuple[str, ...] = (
    "per_game",
    "availability_adjusted",
    "expected_games",
    "role_usage",
    "playoff_schedule",
    "consensus",
    "team_environment",
    "category_scarcity",
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class PlayerInputs:
    """Everything compute_composite needs about one player, bundled from Tasks 8-12."""

    value: PlayerValue
    availability: Availability
    playoff: PlayoffValue
    consensus: ConsensusResult | None
    projection: AdjustedProjection
    rookie_flags: RookieFlags | None


@dataclass(frozen=True)
class CompositeResult:
    """One player's composite score, confidence, and model-vs-consensus context."""

    component_scores: dict[str, float | None]
    component_contributions: dict[str, float]
    model_score: float
    model_rank: int
    final_score: float
    final_rank: int
    confidence: int
    confidence_band: str
    disagreement: Disagreement


def _rank(pids: list[str], score: dict[str, float], per_game_value: dict[str, float]) -> dict[str, int]:
    # tie-break (higher per_game_value, then pid asc) makes every player's sort
    # key unique, so "dense 1..N" is just each player's position in this order
    ordered = sorted(pids, key=lambda p: (-score[p], -per_game_value[p], p))
    return {pid: i + 1 for i, pid in enumerate(ordered)}


def _confidence(inputs: PlayerInputs, settings: Settings) -> tuple[int, str]:
    is_rookie = inputs.rookie_flags is not None and inputs.rookie_flags.rookie
    # a rookie's synthetic baseline has no NBA sample to score, so rookie
    # projection_confidence stands in for sample_size_score
    sample_part = (
        inputs.rookie_flags.projection_confidence
        if is_rookie
        else inputs.projection.pre_adjustment.sample_size_score
    )
    injury_part = inputs.availability.confidence
    # for rookies this already equals projection_confidence (see rookies.py's
    # synthetic RoleChange), so no separate rookie branch is needed here
    role_part = inputs.projection.role_change.confidence

    if inputs.consensus is None or inputs.consensus.rank_variance is None:
        agreement_part = 0.5
    else:
        # 40 ~= the rank-spread (in variance-sqrt units) at which agreement bottoms out
        agreement_part = _clamp(1 - math.sqrt(inputs.consensus.rank_variance) / 40, 0.0, 1.0)

    w = settings.confidence_weights
    raw = (
        w.sample * sample_part
        + w.injury * injury_part
        + w.role * role_part
        + w.source_agreement * agreement_part
    )
    confidence = round(100 * _clamp(raw, 0.0, 1.0))

    bands = settings.confidence_bands
    if confidence >= bands.high:
        band = "HIGH"
    elif confidence >= bands.medium:
        band = "MEDIUM"
    else:
        band = "LOW"
    return confidence, band


def compute_composite(
    inputs: dict[str, PlayerInputs],
    settings: Settings,
    max_consensus_list_length: int = 0,
) -> dict[str, CompositeResult]:
    """Score, rank, and confidence-band every player in the pool.

    `max_consensus_list_length` is the longest published consensus list's
    player count for this run (pipeline.py derives it from the evidence
    store) -- used only to impute a no-consensus player's rank (H4); it has
    no real-world meaning in isolation and defaults to 0 for callers/tests
    that don't exercise a mixed consensus/no-consensus pool.
    """
    pids = list(inputs.keys())
    weights = settings.composite_weights.model_dump()

    per_game_z = dict(
        zip(pids, population_zscores([inputs[p].value.per_game_value for p in pids]))
    )
    availability_adjusted_z = dict(
        zip(pids, population_zscores([inputs[p].value.availability_adjusted_value for p in pids]))
    )
    expected_games_z = dict(
        zip(
            pids,
            population_zscores(
                [float(inputs[p].availability.injury_adjusted_games) for p in pids]
            ),
        )
    )
    # B2 fix: team_environment is a bounded nudge, not a z-score. pace_multiplier
    # is already capped upstream (environment.py) to +-adjustment_caps.pace_multiplier
    # around 1.0, so z-standardizing that capped delta against the pool's own
    # variance would launder a +-5% cap into +-6 sigma of ranking pull once the
    # pool is mostly unchanged (std near 0) -- rescale the already-bounded delta
    # straight into [-1, 1] instead, the same "capped nudge" scale role_usage uses
    pace_cap = settings.adjustment_caps.pace_multiplier
    team_environment_nudge = {
        p: _clamp((inputs[p].projection.pace_multiplier - 1.0) / pace_cap, -1.0, 1.0) for p in pids
    }

    # consensus z is standardized only over the subset that actually has a
    # rank, then negated: a lower (better) rank should map to a higher z
    consensus_pids = [
        p
        for p in pids
        if inputs[p].consensus is not None and inputs[p].consensus.consensus_rank is not None
    ]
    real_consensus_ranks = [
        inputs[p].consensus.consensus_rank for p in consensus_pids  # type: ignore[union-attr]
    ]
    consensus_z_raw = population_zscores(real_consensus_ranks)
    consensus_z = {p: -z for p, z in zip(consensus_pids, consensus_z_raw)}

    # H4: a player absent from every consensus source no longer gets the
    # consensus weight silently redistributed away (that rewarded absence --
    # a player nobody ranked shouldn't score as if consensus were neutral on
    # them). Instead impute a rank one worse than the deepest real list plus
    # the standard per-list imputation penalty, then map that rank into a z
    # against the real population's own mean/std -- symmetric with
    # consensus.py's own per-list imputation, computed once for the whole pool.
    if consensus_pids:
        real_mean = sum(real_consensus_ranks) / len(real_consensus_ranks)
        real_variance = sum((r - real_mean) ** 2 for r in real_consensus_ranks) / len(
            real_consensus_ranks
        )
        real_std = real_variance**0.5
        rank_for_imputation = max_consensus_list_length + settings.consensus.imputation_penalty
        imputed_z = 0.0 if real_std == 0 else -(rank_for_imputation - real_mean) / real_std
        for pid in pids:
            if pid not in consensus_pids:
                consensus_z[pid] = imputed_z

    component_scores: dict[str, dict[str, float | None]] = {}
    for pid in pids:
        pi = inputs[pid]
        component_scores[pid] = {
            "per_game": per_game_z[pid],
            "availability_adjusted": availability_adjusted_z[pid],
            "expected_games": expected_games_z[pid],
            # already scaled to [-1, 1] by roles.py -- comparable to a z on
            # this blend's scale, not re-standardized
            "role_usage": pi.projection.role_change.score,
            "playoff_schedule": pi.playoff.playoff_value,
            "consensus": consensus_z.get(pid),
            "team_environment": team_environment_nudge[pid],
            "category_scarcity": pi.value.scarcity_score,
        }

    # component scales, before the weighted blend below: per_game,
    # availability_adjusted, expected_games, and consensus are population
    # z-scores (unbounded, pool-relative); role_usage and team_environment are
    # bounded [-1, 1] capped nudges (deliberately small, fixed-scale signals,
    # not standardized against the pool); playoff_schedule and
    # category_scarcity are also pool-relative population z-scores computed
    # upstream (playoffs.py / ninecat.py). Weights below are each component's
    # relative influence WITHIN its own scale -- a bounded nudge's weight
    # caps its max possible pull at that weight, while a z component's actual
    # pull still depends on how spread out the pool is on that quantity.
    per_game_value = {pid: inputs[pid].value.per_game_value for pid in pids}
    final_score: dict[str, float] = {}
    model_score: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {}

    for pid in pids:
        scores = component_scores[pid]
        present = {k: v for k, v in scores.items() if v is not None}

        # D6/no-consensus redistribution: renormalize settings weights over
        # only the components this player actually has, so a missing
        # playoff_schedule or consensus never silently shrinks the score
        weight_sum = sum(weights[k] for k in present)
        renorm = {k: weights[k] / weight_sum for k in present}
        contributions[pid] = {k: renorm[k] * present[k] for k in present}
        final_score[pid] = sum(contributions[pid].values())

        # model_score always excludes consensus (even when present) -- the
        # pure-statistics rank, kept visible alongside the consensus-blended one
        present_no_consensus = {k: v for k, v in present.items() if k != "consensus"}
        weight_sum_no_consensus = sum(weights[k] for k in present_no_consensus)
        renorm_no_consensus = {
            k: weights[k] / weight_sum_no_consensus for k in present_no_consensus
        }
        model_score[pid] = sum(
            renorm_no_consensus[k] * present_no_consensus[k] for k in present_no_consensus
        )

    final_rank = _rank(pids, final_score, per_game_value)
    model_rank = _rank(pids, model_score, per_game_value)

    results: dict[str, CompositeResult] = {}
    for pid in pids:
        pi = inputs[pid]
        confidence, band = _confidence(pi, settings)
        consensus_rank = pi.consensus.consensus_rank if pi.consensus is not None else None
        rank_variance = pi.consensus.rank_variance if pi.consensus is not None else None
        disagree = compute_disagreement(model_rank[pid], consensus_rank, rank_variance, settings)
        results[pid] = CompositeResult(
            component_scores=component_scores[pid],
            component_contributions=contributions[pid],
            model_score=model_score[pid],
            model_rank=model_rank[pid],
            final_score=final_score[pid],
            final_rank=final_rank[pid],
            confidence=confidence,
            confidence_band=band,
            disagreement=disagree,
        )
    return results
