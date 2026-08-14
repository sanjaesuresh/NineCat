"""Rookie projection: seed a fresh player from analyst evidence rather than NBA
history (Task 9).

Rookies have no SeasonLine history, so they can't flow through project_baseline
(Task 6). Instead this module builds a synthetic BaselineProjection directly
from a RookieNote's minutes range and per-minute rate band, wraps it in the
same AdjustedProjection shape as Task 7's role adjustment, and attaches
RookieFlags recording how little certainty backs the projection. A note
without both a minutes range and a full rate band is excluded from the pool
rather than projected with invented numbers (spec's evidence-only principle).
"""

from __future__ import annotations

from dataclasses import dataclass

from nineproj.config import Settings
from nineproj.models.baseline import STAT_FIELDS, BaselineProjection
from nineproj.models.roles import AdjustedProjection, RoleChange
from nineproj.research.schema import RookieNote

# rookie confidence is always kept below the 0.7 "no role evidence" default in
# roles.py -- even a well-evidenced rookie note is a projection of unseen NBA
# production, never as certain as "this vet keeps last year's role"
_CONFIDENCE_FLOOR = 0.2
_CONFIDENCE_CEILING = 0.6
_BASE_CONFIDENCE = 0.3
_TOP5_PICK_BONUS = 0.15
_NARROW_RANGE_BONUS = 0.1
_NARROW_RANGE_MAX_WIDTH = 6.0

# role_uncertainty scales with the width of the projected minutes range: a
# wide range (bench-or-starter battle) means the whole per-game line is shaky
_UNCERTAINTY_FLOOR = 0.3
_UNCERTAINTY_CEILING = 0.9
_UNCERTAINTY_WIDTH_DIVISOR = 12.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class RookieFlags:
    """Marks a projection as rookie-sourced and records its extra uncertainty."""

    rookie: bool
    projection_confidence: float
    role_uncertainty: float


def project_rookie(note: RookieNote, settings: Settings) -> tuple[AdjustedProjection, RookieFlags] | None:
    """Build an AdjustedProjection straight from a rookie's evidence note.

    Returns None when the note lacks a minutes range or a complete per-minute
    band -- both are schema-optional (partial evidence is legal to record),
    but without them there is no evidence-backed number to project, and the
    spec requires exclusion over invention for evidence-free rookies.
    """
    if note.minutes_range is None or note.per_minute_band is None:
        return None
    if not set(STAT_FIELDS) <= note.per_minute_band.keys():
        return None

    low, high = note.minutes_range
    minutes = (low + high) / 2.0

    per_game = {stat: note.per_minute_band[stat] * minutes for stat in STAT_FIELDS}
    # analyst-derived rate bands are eyeballed independently per stat and can
    # imply makes > attempts; clamp makes down rather than trust the band's
    # internal consistency
    per_game["fgm"] = min(per_game["fgm"], per_game["fga"])
    per_game["ftm"] = min(per_game["ftm"], per_game["fta"])

    # synthetic baseline: sample_size_score 0.0 / seasons_used [] mark "no NBA
    # history" explicitly, distinguishing this from a real regressed baseline
    baseline = BaselineProjection(
        minutes=minutes,
        games=None,
        sample_size_score=0.0,
        seasons_used=[],
        **per_game,
    )

    width = high - low
    projection_confidence = _clamp(
        _BASE_CONFIDENCE
        + (_TOP5_PICK_BONUS if note.draft_pick is not None and note.draft_pick <= 5 else 0.0)
        + (_NARROW_RANGE_BONUS if width <= _NARROW_RANGE_MAX_WIDTH else 0.0),
        _CONFIDENCE_FLOOR,
        _CONFIDENCE_CEILING,
    )
    role_uncertainty = _clamp(
        width / _UNCERTAINTY_WIDTH_DIVISOR, _UNCERTAINTY_FLOOR, _UNCERTAINTY_CEILING
    )

    role_change = RoleChange(
        direction="neutral",
        score=0.0,
        minutes_delta=0.0,
        usage_delta=0.0,
        confidence=projection_confidence,
    )
    adjusted = AdjustedProjection(
        minutes=minutes,
        pre_adjustment=baseline,
        role_change=role_change,
        pace_multiplier=1.0,
        **per_game,
    )
    flags = RookieFlags(
        rookie=True,
        projection_confidence=projection_confidence,
        role_uncertainty=role_uncertainty,
    )
    return adjusted, flags
