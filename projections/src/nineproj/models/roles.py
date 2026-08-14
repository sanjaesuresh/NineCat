"""Role/team-change adjustment: rescale a baseline by evidence-backed minutes
and usage deltas (Task 7).

Combines every RoleNote for a player into one capped minutes/usage delta,
rescales the baseline's per-game rates, and records the pre-adjustment values
plus the RoleChange itself so the exporter can show every step (spec's
transparency principle). Pure function -- no I/O, no mutation of the RoleNote
objects passed in.
"""

from __future__ import annotations

from dataclasses import dataclass

from nineproj.config import Settings
from nineproj.models.baseline import BaselineProjection
from nineproj.research.schema import RoleNote

# stats the usage factor applies to directly (creation/possession-using stats);
# fgm/ftm are rederived below to keep shooting percentages intact
_USAGE_STATS: tuple[str, ...] = ("fga", "fta", "tpm", "pts", "tov")

# a player with no role evidence is assumed to keep a stable role; 0.7 (not
# 1.0) reflects that "no news" still isn't full certainty about next season
_DEFAULT_STABLE_CONFIDENCE = 0.7

# minutes are clamped to a realistic single-game ceiling/floor regardless of
# how large the (already-capped) delta is
_MIN_MINUTES = 0.0
_MAX_MINUTES = 40.0

# usage_delta is expressed in percentage points of a ~25%-usage league-average
# workload, so a note's usage_delta maps onto the creation-stat factor below
_LEAGUE_AVERAGE_USAGE = 25.0

# below this |score| the direction is reported as "neutral" rather than a
# barely-nonzero positive/negative
_DIRECTION_THRESHOLD = 0.05


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class RoleChange:
    """Combined role/usage signal from a player's RoleNote evidence."""

    direction: str
    score: float
    minutes_delta: float
    usage_delta: float
    confidence: float


@dataclass(frozen=True)
class AdjustedProjection:
    """A BaselineProjection rescaled by a RoleChange, keeping every step visible."""

    minutes: float
    fgm: float
    fga: float
    ftm: float
    fta: float
    tpm: float
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    tov: float
    pre_adjustment: BaselineProjection
    role_change: RoleChange
    pace_multiplier: float


def _combine_notes(role_notes: list[RoleNote], settings: Settings) -> tuple[float, float, float]:
    """Weighted mean of (minutes_delta, usage_delta, confidence) across notes.

    Per-note weight = (note.weight or a default low-confidence-source weight)
    x note.confidence, so a highly-confident, high-quality-tier note dominates
    a shaky/low-tier one. A minutes_delta sign conflict between any two notes
    multiplies the combined confidence by 0.7 (an unresolved disagreement is
    inherently less trustworthy than either note alone).
    """
    weighted_minutes = 0.0
    weighted_usage = 0.0
    weighted_confidence = 0.0
    weight_total = 0.0
    for note in role_notes:
        # 0.15 mirrors the "low" quality-tier weight (config.py consensus.quality_tier_weights)
        # as a conservative default when a note has no loader-assigned weight
        weight = (note.weight if note.weight is not None else 0.15) * note.confidence
        weighted_minutes += weight * note.minutes_delta
        weighted_usage += weight * note.usage_delta
        weighted_confidence += weight * note.confidence
        weight_total += weight

    if weight_total <= 0:
        return 0.0, 0.0, _DEFAULT_STABLE_CONFIDENCE

    minutes_delta = weighted_minutes / weight_total
    usage_delta = weighted_usage / weight_total
    confidence = weighted_confidence / weight_total

    has_positive = any(n.minutes_delta > 0 for n in role_notes)
    has_negative = any(n.minutes_delta < 0 for n in role_notes)
    if has_positive and has_negative:
        confidence *= 0.7

    caps = settings.adjustment_caps
    minutes_delta = _clamp(minutes_delta, -caps.minutes_delta, caps.minutes_delta)
    usage_delta = _clamp(usage_delta, -caps.usage_delta, caps.usage_delta)
    return minutes_delta, usage_delta, confidence


def apply_role_adjustment(
    baseline: BaselineProjection, role_notes: list[RoleNote], settings: Settings
) -> AdjustedProjection:
    """Rescale a baseline projection by its combined role/usage evidence."""
    caps = settings.adjustment_caps

    if not role_notes:
        role_change = RoleChange(
            direction="neutral",
            score=0.0,
            minutes_delta=0.0,
            usage_delta=0.0,
            confidence=_DEFAULT_STABLE_CONFIDENCE,
        )
        return AdjustedProjection(
            minutes=baseline.minutes,
            fgm=baseline.fgm,
            fga=baseline.fga,
            ftm=baseline.ftm,
            fta=baseline.fta,
            tpm=baseline.tpm,
            pts=baseline.pts,
            reb=baseline.reb,
            ast=baseline.ast,
            stl=baseline.stl,
            blk=baseline.blk,
            tov=baseline.tov,
            pre_adjustment=baseline,
            role_change=role_change,
            pace_multiplier=1.0,
        )

    minutes_delta, usage_delta, confidence = _combine_notes(role_notes, settings)

    # step 1: minutes scaling first, all 11 stats move with playing time so
    # per-minute rates are preserved; a 0-minute baseline has no rate to scale
    new_minutes = _clamp(baseline.minutes + minutes_delta, _MIN_MINUTES, _MAX_MINUTES)
    minutes_factor = new_minutes / baseline.minutes if baseline.minutes > 0 else 0.0
    scaled = {
        stat: getattr(baseline, stat) * minutes_factor
        for stat in ("fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov")
    }

    # step 2: usage factor applied only to creation stats, after minutes scaling
    usage_factor = 1 + usage_delta / _LEAGUE_AVERAGE_USAGE
    for stat in _USAGE_STATS:
        scaled[stat] *= usage_factor

    # rederive makes from the baseline's own shooting percentages so usage
    # changes volume without silently changing accuracy
    fg_pct = baseline.fgm / baseline.fga if baseline.fga > 0 else 0.0
    ft_pct = baseline.ftm / baseline.fta if baseline.fta > 0 else 0.0
    scaled["fgm"] = scaled["fga"] * fg_pct
    scaled["ftm"] = scaled["fta"] * ft_pct

    score = _clamp(
        0.5 * (minutes_delta / caps.minutes_delta) + 0.5 * (usage_delta / caps.usage_delta),
        -1.0,
        1.0,
    )
    if score > _DIRECTION_THRESHOLD:
        direction = "positive"
    elif score < -_DIRECTION_THRESHOLD:
        direction = "negative"
    else:
        direction = "neutral"

    role_change = RoleChange(
        direction=direction,
        score=score,
        minutes_delta=minutes_delta,
        usage_delta=usage_delta,
        confidence=confidence,
    )
    return AdjustedProjection(
        minutes=new_minutes,
        pre_adjustment=baseline,
        role_change=role_change,
        pace_multiplier=1.0,
        **scaled,
    )
