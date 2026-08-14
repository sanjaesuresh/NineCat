"""Template-driven strengths/risks/paragraph explanation for one player's
composite score (Task 13).

Every sentence is assembled from actual stored values -- per-game z-scores,
availability numbers, disagreement flags, playoff z -- via deterministic
f-string templates. No free-form narrative claim is ever made without a
number backing it. Pure function, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninecat.engine.zscores import CATEGORIES

from nineproj.config import Settings
from nineproj.value.composite import CompositeResult, PlayerInputs

# CATEGORIES order is fg_pct, ft_pct, tpm, pts, reb, ast, stl, blk, tov;
# display names deliberately diverge from the raw keys (ST not STL, TO not TOV)
_CATEGORY_DISPLAY: dict[str, str] = {
    "fg_pct": "FG%",
    "ft_pct": "FT%",
    "tpm": "3PM",
    "pts": "PTS",
    "reb": "REB",
    "ast": "AST",
    "stl": "ST",
    "blk": "BLK",
    "tov": "TO",
}

# human labels for the composite's 8 component keys, used only in the
# generated paragraph's "driven mainly by ..." clause
_COMPONENT_LABELS: dict[str, str] = {
    "per_game": "per-game production",
    "availability_adjusted": "availability-adjusted value",
    "expected_games": "expected games played",
    "role_usage": "role/usage change",
    "playoff_schedule": "playoff schedule",
    "consensus": "consensus ranking",
    "team_environment": "team pace",
    "category_scarcity": "category scarcity",
}

_STRENGTH_THRESHOLD = 0.5
_ELITE_THRESHOLD = 1.5
_WEAK_THRESHOLD = -1.0
_MAX_STRENGTHS = 4
_LIMITED_AVAILABILITY_GAMES = 60


@dataclass(frozen=True)
class Explanation:
    strengths: list[str]
    risks: list[str]
    paragraph: str


def _ranked_categories(inputs: PlayerInputs, *, at_least: float) -> list[tuple[str, float]]:
    zscores = inputs.value.per_game_zscores
    return [(cat, zscores[cat]) for cat in CATEGORIES if cat in zscores and zscores[cat] >= at_least]


def _strengths(inputs: PlayerInputs) -> list[str]:
    ranked = sorted(
        _ranked_categories(inputs, at_least=_STRENGTH_THRESHOLD), key=lambda kv: kv[1], reverse=True
    )
    strengths = []
    for cat, z in ranked[:_MAX_STRENGTHS]:
        label = "elite" if z >= _ELITE_THRESHOLD else "strong"
        strengths.append(f"{label} {_CATEGORY_DISPLAY[cat]} ({z:+.1f}z)")
    return strengths


def _risks(inputs: PlayerInputs, result: CompositeResult) -> list[str]:
    risks: list[str] = []
    availability = inputs.availability

    if availability.injury_risk_label != "low":
        risks.append(
            f"moderate/high injury risk (score {availability.injury_risk_score:.2f}, "
            f"{availability.injury_adjusted_games} projected games)"
        )

    # high_uncertainty only fires from a real, present rank_variance (see
    # value.consensus.disagreement), so inputs.consensus is guaranteed here
    if result.disagreement.flag == "high_uncertainty" and inputs.consensus is not None:
        risks.append(f"sources disagree widely (variance {inputs.consensus.rank_variance:.0f})")

    if inputs.rookie_flags is not None and inputs.rookie_flags.rookie:
        risks.append(f"rookie projection (confidence {inputs.rookie_flags.projection_confidence:.2f})")

    if availability.injury_adjusted_games < _LIMITED_AVAILABILITY_GAMES:
        risks.append(f"limited availability ({availability.injury_adjusted_games} games)")

    zscores = inputs.value.per_game_zscores
    weak = sorted(
        ((cat, zscores[cat]) for cat in CATEGORIES if cat in zscores and zscores[cat] <= _WEAK_THRESHOLD),
        key=lambda kv: kv[1],  # worst (most negative) first
    )
    for cat, z in weak:
        risks.append(f"weak {_CATEGORY_DISPLAY[cat]} ({z:+.1f}z)")

    return risks


def _paragraph(name: str, inputs: PlayerInputs, result: CompositeResult, settings: Settings) -> str:
    sentences: list[str] = []

    # H5: "driven mainly by" must never present a drag as a driver -- take the
    # top 2 contributions by |value| as before, but only the positive ones
    # become drivers; any negative one in that top 2 gets its own "held back
    # by" clause instead, so a big negative team_environment (say) is never
    # phrased as something that helped the player's rank
    top_components = sorted(
        result.component_contributions.items(), key=lambda kv: abs(kv[1]), reverse=True
    )[:2]
    driver_labels = [_COMPONENT_LABELS[k] for k, v in top_components if v > 0]
    drag_labels = [_COMPONENT_LABELS[k] for k, v in top_components if v < 0]
    driver_text = " and ".join(driver_labels) if driver_labels else "the composite blend"

    games = inputs.availability.injury_adjusted_games
    headline = (
        f"{name} ranks #{result.final_rank} overall, projected for {games} games, "
        f"driven mainly by {driver_text}"
    )
    if drag_labels:
        headline += f", held back by {' and '.join(drag_labels)}"
    strengths_ranked = sorted(
        _ranked_categories(inputs, at_least=_STRENGTH_THRESHOLD), key=lambda kv: kv[1], reverse=True
    )
    if strengths_ranked:
        top_cat, top_z = strengths_ranked[0]
        headline += f", with {_CATEGORY_DISPLAY[top_cat]} as the top category ({top_z:+.1f}z)."
    else:
        headline += "."
    sentences.append(headline)

    # model-vs-consensus gap: only when the composite layer's own threshold
    # check (baked into disagreement.flag) actually flagged model_loves/fades
    if (
        result.disagreement.flag in ("model_loves", "model_fades")
        and inputs.consensus is not None
        and inputs.consensus.consensus_rank is not None
        and result.disagreement.rank_difference is not None
    ):
        gap = abs(result.disagreement.rank_difference)
        direction = "higher" if result.disagreement.flag == "model_loves" else "lower"
        consensus_rank_display = round(inputs.consensus.consensus_rank)
        top_label = driver_labels[0] if driver_labels else "the composite blend"
        sentences.append(
            f"Model is {gap:.0f} spots {direction} than consensus "
            f"(#{result.model_rank} vs #{consensus_rank_display}), driven by {top_label}."
        )

    # playoff-window note: only when there's something notable (no schedule
    # yet, or a materially favorable/light window) to actually report; season
    # and week range come from settings so a config change is reflected here
    playoff_value = inputs.playoff.playoff_value
    window_label = f"Week {settings.playoff_window.start_week}-{settings.playoff_window.end_week}"
    if playoff_value is None:
        sentences.append(
            f"{settings.season} playoff schedule not yet published — playoff weight redistributed."
        )
    elif abs(playoff_value) >= 1.0:
        descriptor = "Favorable" if playoff_value > 0 else "Light"
        sentences.append(f"{descriptor} {window_label} schedule.")

    return " ".join(sentences)


def explain(
    pid_display_name: str, inputs: PlayerInputs, result: CompositeResult, settings: Settings
) -> Explanation:
    """Build a template-driven strengths/risks/paragraph explanation for one player."""
    return Explanation(
        strengths=_strengths(inputs),
        risks=_risks(inputs, result),
        paragraph=_paragraph(pid_display_name, inputs, result, settings),
    )
