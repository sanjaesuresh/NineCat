"""Pydantic schema for research evidence notes (Task 4).

These models describe analyst/community research evidence -- consensus
rankings, transactions, injuries, role notes, rookie notes, and forum
sentiment -- that feeds the projection composite alongside the statistical
baseline. All models reject unknown keys (extra="forbid") so a typo in a
research JSON fixture fails loudly at load time instead of being silently
ignored.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator

# mirrors the six tier keys in Settings.consensus.quality_tier_weights (config.py)
QualityTier = Literal["very_high", "high", "medium_high", "medium", "low_medium", "low"]
# mirrors the six type keys in Settings.consensus.source_type_weights (config.py)
SourceType = Literal[
    "statistical_model", "expert_rank", "projection", "adp", "community_rank", "news"
]
SeasonLabel = Literal["2026-27", "2025-26", "mixed"]

# the 11 box-score stat keys a rookie per-minute rate band may cover
STAT_KEYS = frozenset(
    {"fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov"}
)


class _EvidenceModel(BaseModel):
    """Shared base: rejects unknown keys so a JSON typo fails loudly."""

    model_config = ConfigDict(extra="forbid")


class SourceRef(_EvidenceModel):
    """Provenance for one piece of research evidence."""

    source: str
    url: str
    retrieved: str
    season_label: SeasonLabel
    quality_tier: QualityTier
    type: SourceType

    @field_validator("url")
    @classmethod
    def _url_must_be_http(cls, v: str) -> str:
        # startswith("http") alone would accept junk like "httpgarbage-not-a-real-url";
        # parse it properly and require both a real http(s) scheme and a host
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"url must be a valid http(s) URL, got {v!r}")
        return v


class ConsensusList(_EvidenceModel):
    """An ordered player-name ranking from one source; rank = index + 1."""

    source: SourceRef
    players: list[str]


class TransactionEvent(_EvidenceModel):
    player: str
    from_team: str | None = None
    to_team: str | None = None
    kind: Literal["trade", "signing", "draft", "retirement", "coaching_change"]
    date: str
    source: SourceRef
    note: str | None = None
    # attached by store.load_store from settings.quality_tier_weights[source.quality_tier];
    # never present in the raw research JSON; None (not 0.0) until loaded, so
    # arithmetic on a directly-constructed item fails loudly instead of
    # silently zero-weighting
    weight: float | None = None


class InjuryNote(_EvidenceModel):
    player: str
    status: str
    # games expected missed, only set when a source states an explicit timeline
    games_impact_estimate: int | None = None
    chronic: bool
    source: SourceRef
    note: str | None = None
    weight: float | None = None


class RoleNote(_EvidenceModel):
    player: str
    direction: Literal["positive", "negative", "neutral"]
    minutes_delta: float
    usage_delta: float
    confidence: float
    rationale: str
    source: SourceRef
    weight: float | None = None

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {v}")
        return v


class RookieNote(_EvidenceModel):
    player: str
    draft_pick: int | None = None
    team: str
    position: str | None = None
    expected_role: str
    minutes_range: tuple[float, float] | None = None
    comps: list[str] = []
    # conservative analyst-derived per-minute rates; optional, only present when a source estimates them
    per_minute_band: dict[str, float] | None = None
    source: SourceRef
    weight: float | None = None

    @field_validator("per_minute_band")
    @classmethod
    def _per_minute_band_keys_known(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return v
        unknown = set(v) - STAT_KEYS
        if unknown:
            raise ValueError(f"per_minute_band has unknown stat keys: {sorted(unknown)}")
        return v


class SentimentNote(_EvidenceModel):
    player: str
    stance: Literal[
        "breakout", "bust", "injury_concern", "rank_higher", "rank_lower", "role_change"
    ]
    strength: Literal["recurring", "one_off"]
    thread_url: str
    thread_date: str | None = None
    paraphrase: str
    source: SourceRef
    weight: float | None = None
