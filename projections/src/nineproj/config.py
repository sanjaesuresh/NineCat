"""Immutable settings loader for the projection pipeline.

Every later task in projections/ consumes the frozen `Settings` object
returned by `load_settings`, so this module is the single source of truth
for defaults (composite weights, playoff window, caps, etc.) that live in
projections/config/settings.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

# shared base: every settings model is frozen (immutable after load) and
# rejects unknown keys so a typo in settings.json fails loudly instead of
# silently being ignored.
class _StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CompositeWeights(_StrictModel):
    per_game: float
    availability_adjusted: float
    expected_games: float
    role_usage: float
    playoff_schedule: float
    consensus: float
    team_environment: float
    category_scarcity: float


class ValueSplit(_StrictModel):
    regular_season: float
    playoff: float


class PlayoffWindow(_StrictModel):
    start_week: int
    end_week: int


class ConsensusSourceTypeWeights(_StrictModel):
    statistical_model: float
    expert_rank: float
    projection: float
    adp: float
    community_rank: float
    news: float


class QualityTierWeights(_StrictModel):
    very_high: float
    high: float
    medium_high: float
    medium: float
    low_medium: float
    low: float


class Consensus(_StrictModel):
    source_type_weights: ConsensusSourceTypeWeights
    quality_tier_weights: QualityTierWeights
    # rank gap (spots) beyond which model_loves/model_fades flags fire
    disagreement_rank_threshold: int
    # rank variance above which a player is flagged high_uncertainty
    high_variance_threshold: float
    # rank penalty added past list length when a source omits a player
    imputation_penalty: int


class AgeCurve(_StrictModel):
    improve_until: int
    decline_after: int
    steep_decline_after: int
    young_bonus: float
    old_penalty: float
    steep_penalty: float
    # clamp on the final age multiplier so extreme ages can't distort rates
    multiplier_floor: float
    multiplier_ceiling: float


class Baseline(_StrictModel):
    blend_weights: tuple[float, float, float]
    regression_strength: float
    # career minutes at which a blend counts as a full sample (no regression)
    full_sample_minutes: int
    # a veteran whose total blend-window minutes (Sigma games*minutes across
    # their lines) falls under this never enters the valuation pool -- a
    # 3-game cameo can't rank alongside a real sample (B3); rookies (the
    # evidence-band path) are exempt since they have no NBA minutes at all
    min_rankable_minutes: int
    age_curve: AgeCurve


class AdjustmentCaps(_StrictModel):
    minutes_delta: float
    usage_delta: float
    pace_multiplier: float


class AvailabilityRiskThresholds(_StrictModel):
    low: float
    moderate: float


class AvailabilityAgePenalties(_StrictModel):
    under_28: float
    from_28_to_31: float
    from_32_to_34: float
    over_34: float


class Availability(_StrictModel):
    risk_thresholds: AvailabilityRiskThresholds
    league_median_games: int
    regression_games: int
    # how much of the raw games projection a max-risk player loses
    shrink_factor: float
    # weight of historical missed-game share inside the risk score
    missed_share_weight: float
    chronic_penalty: float
    # ceiling on the risk contribution of a currently reported absence
    current_injury_risk_cap: float
    age_penalties: AvailabilityAgePenalties


class ConfidenceBands(_StrictModel):
    high: int
    medium: int


class ConfidenceWeights(_StrictModel):
    sample: float
    injury: float
    role: float
    source_agreement: float


class Cache(_StrictModel):
    ttl_hours: int


class GamesBounds(_StrictModel):
    min: int
    max: int


class Settings(_StrictModel):
    season: str
    prior_seasons: tuple[str, str, str]
    composite_weights: CompositeWeights
    value_split: ValueSplit
    playoff_window: PlayoffWindow
    # dashboard-selectable playoff-window options (start_week, end_week pairs);
    # the pipeline precomputes every candidate's schedule.windows entry so the
    # dashboard can swap windows client-side without a re-run
    candidate_playoff_windows: tuple[tuple[int, int], ...]
    fantasy_week1_start: str
    consensus: Consensus
    baseline: Baseline
    adjustment_caps: AdjustmentCaps
    availability: Availability
    confidence_bands: ConfidenceBands
    confidence_weights: ConfidenceWeights
    cache: Cache
    games_bounds: GamesBounds
    # z-score bar a category must clear to count as a player's "strength" for
    # category_scarcity_weights (ninecat.py); a real settings field (not a
    # hardcoded module constant) so it's actually driven by the settings param
    # every caller already threads through
    scarcity_z_threshold: float

    @model_validator(mode="after")
    def _validate_weights_and_window(self) -> "Settings":
        # composite weights must form a complete 1.0 blend (Global Constraints)
        composite_total = sum(self.composite_weights.model_dump().values())
        if abs(composite_total - 1.0) > 1e-9:
            raise ValueError(
                f"composite_weights must sum to 1.0, got {composite_total}"
            )

        # regular season / playoff value split must also fully partition 1.0
        split_total = self.value_split.regular_season + self.value_split.playoff
        if abs(split_total - 1.0) > 1e-9:
            raise ValueError(f"value_split must sum to 1.0, got {split_total}")

        if self.playoff_window.start_week > self.playoff_window.end_week:
            raise ValueError(
                "playoff_window.start_week must be <= end_week, got "
                f"start_week={self.playoff_window.start_week} "
                f"end_week={self.playoff_window.end_week}"
            )

        # every candidate window must itself be a valid (start <= end) range,
        # and the primary playoff_window must be one of the dashboard's
        # selectable options -- otherwise the shipped default couldn't be
        # reselected after picking something else
        bad_windows = [w for w in self.candidate_playoff_windows if w[0] > w[1]]
        if bad_windows:
            raise ValueError(f"candidate_playoff_windows entries must have start <= end, got {bad_windows}")
        primary_window = (self.playoff_window.start_week, self.playoff_window.end_week)
        if primary_window not in self.candidate_playoff_windows:
            raise ValueError(
                f"playoff_window {primary_window} must appear in candidate_playoff_windows "
                f"{self.candidate_playoff_windows}"
            )

        # guard against negative weights anywhere in the weighted sections
        all_weights = {
            **self.composite_weights.model_dump(),
            **self.value_split.model_dump(),
            **self.consensus.source_type_weights.model_dump(),
            **self.consensus.quality_tier_weights.model_dump(),
        }
        negative = {k: v for k, v in all_weights.items() if v < 0}
        if negative:
            raise ValueError(f"weights must be non-negative, got negative values: {negative}")

        return self


def load_settings(path: str | Path) -> Settings:
    """Load and validate the projection pipeline settings from a JSON file.

    Raises pydantic's ValidationError (via Settings(**data)) on unknown keys,
    malformed types, or a failed cross-field validation rule (weight sums,
    playoff window ordering, non-negative weights).
    """
    data = json.loads(Path(path).read_text())
    return Settings(**data)
