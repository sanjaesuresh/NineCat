"""Games-played and injury-risk projection (Task 8).

`raw_projected_games` is a recency-weighted, lightly regressed blend of the
last three seasons' games-played; `injury_risk_score`/`injury_adjusted_games`
fold in age, a chronic-condition flag, and any currently reported injury
timeline from research evidence. Pure function -- no I/O, no mutation of the
InjuryNote objects passed in. Every constant comes from settings.availability
/ settings.games_bounds (no new magic numbers).
"""

from __future__ import annotations

from dataclasses import dataclass

from nineproj.config import Settings
from nineproj.data.nba_stats import SeasonLine
from nineproj.research.schema import InjuryNote


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class Availability:
    """Games-played and injury-risk projection for one player.

    Raw and adjusted games are both kept (spec section 9: transparency) so
    downstream composite math can see the pre- and post-risk-shrink numbers.
    """

    raw_projected_games: float
    injury_risk_score: float
    injury_risk_label: str
    injury_adjusted_games: int
    availability_probability: float
    confidence: float


def _age_penalty(age: int, settings: Settings) -> float:
    penalties = settings.availability.age_penalties
    if age < 28:
        return penalties.under_28
    if age <= 31:
        return penalties.from_28_to_31
    if age <= 34:
        return penalties.from_32_to_34
    return penalties.over_34


def _max_games_impact(injury_notes: list[InjuryNote]) -> int:
    # a note with no explicit timeline (games_impact_estimate=None) contributes
    # nothing to the reported-absence signal, it isn't treated as zero-impact evidence
    estimates = [
        n.games_impact_estimate for n in injury_notes if n.games_impact_estimate is not None
    ]
    return max(estimates, default=0)


def project_availability(
    player_age: int,
    history: dict[str, SeasonLine],
    injury_notes: list[InjuryNote],
    settings: Settings,
) -> Availability:
    """Project games played and injury risk from GP history, age, and evidence.

    `history` is keyed by season string (matching settings.prior_seasons);
    `injury_notes` is assumed already scoped to this one player.
    """
    availability_cfg = settings.availability
    max_games = settings.games_bounds.max
    min_games = settings.games_bounds.min

    present_seasons = [season for season in settings.prior_seasons if season in history]
    has_history = bool(present_seasons)

    if not has_history:
        raw = float(availability_cfg.league_median_games)
    else:
        weights = settings.baseline.blend_weights
        weighted_sum = 0.0
        weight_total = 0.0
        career_games = 0

        # B1: a season strictly more recent than the player's oldest present
        # season but missing from `history` is a real "played zero games"
        # season (a returner's injury/absence year) -- that's information,
        # not a gap, so it still counts at full blend weight with games=0.
        # A season older than the oldest present one has no evidence at all
        # (pre-debut) and stays fully excluded, weight and all.
        oldest_present_index = max(
            i for i, season in enumerate(settings.prior_seasons) if season in history
        )
        for i, (season, weight) in enumerate(zip(settings.prior_seasons, weights)):
            if season in history:
                games = history[season].games
            elif i <= oldest_present_index:
                games = 0
            else:
                continue
            weighted_sum += weight * games
            weight_total += weight
            career_games += games
        raw = weighted_sum / weight_total

        # a thin sample (short career total or a single season on record)
        # regresses halfway to the league median rather than trusting a
        # small-sample blend outright
        if career_games < availability_cfg.regression_games or len(present_seasons) < 2:
            raw = 0.5 * raw + 0.5 * availability_cfg.league_median_games

    raw = _clamp(raw, min_games, max_games)

    missed_share = 1 - raw / max_games
    age_pen = _age_penalty(player_age, settings)
    chronic = availability_cfg.chronic_penalty if any(n.chronic for n in injury_notes) else 0.0
    reported = _max_games_impact(injury_notes)
    current = min(availability_cfg.current_injury_risk_cap, reported / max_games)

    injury_risk_score = _clamp(
        availability_cfg.missed_share_weight * missed_share + age_pen + chronic + current,
        0.0,
        1.0,
    )

    thresholds = availability_cfg.risk_thresholds
    if injury_risk_score < thresholds.low:
        injury_risk_label = "low"
    elif injury_risk_score < thresholds.moderate:
        injury_risk_label = "moderate"
    else:
        injury_risk_label = "high"

    # a currently reported absence sets a hard ceiling (max_games - reported)
    # that historical form can't override, e.g. "out until January"
    ceiling = max_games - reported
    risk_shrunk = raw * (1 - availability_cfg.shrink_factor * injury_risk_score)
    injury_adjusted_games = round(_clamp(min(risk_shrunk, ceiling), min_games, max_games))
    availability_probability = injury_adjusted_games / max_games

    # thin (<3 seasons) history costs confidence beyond what the risk score
    # already implies; total absence of history caps confidence outright
    fewer_than_full_history = len(present_seasons) < len(settings.prior_seasons)
    confidence = _clamp(
        1 - 0.5 * injury_risk_score - (0.2 if fewer_than_full_history else 0.0),
        0.0,
        1.0,
    )
    if not has_history:
        confidence = min(confidence, 0.4)

    return Availability(
        raw_projected_games=raw,
        injury_risk_score=injury_risk_score,
        injury_risk_label=injury_risk_label,
        injury_adjusted_games=injury_adjusted_games,
        availability_probability=availability_probability,
        confidence=confidence,
    )
