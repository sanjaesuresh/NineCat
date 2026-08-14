"""Tests for nineproj.value.explain: template-driven player explanations (Task 13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nineproj.config import Settings, load_settings
from nineproj.models.availability import Availability
from nineproj.models.baseline import BaselineProjection
from nineproj.models.roles import AdjustedProjection, RoleChange
from nineproj.models.rookies import RookieFlags
from nineproj.value.composite import CompositeResult, PlayerInputs
from nineproj.value.consensus import ConsensusResult, Disagreement
from nineproj.value.explain import explain
from nineproj.value.ninecat import PlayerValue
from nineproj.value.playoffs import PlayoffValue

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"

_ZERO_STATS = dict(fgm=0.0, fga=0.0, ftm=0.0, fta=0.0, tpm=0.0, pts=0.0, reb=0.0, ast=0.0, stl=0.0, blk=0.0, tov=0.0)


@pytest.fixture()
def settings() -> Settings:
    return load_settings(SHIPPED_SETTINGS)


def _projection() -> AdjustedProjection:
    baseline = BaselineProjection(
        minutes=30.0, games=None, sample_size_score=1.0, seasons_used=["2025-26"], **_ZERO_STATS
    )
    role_change = RoleChange(direction="neutral", score=0.0, minutes_delta=0.0, usage_delta=0.0, confidence=0.9)
    return AdjustedProjection(
        minutes=30.0, pre_adjustment=baseline, role_change=role_change, pace_multiplier=1.0, **_ZERO_STATS
    )


def _inputs(
    *,
    per_game_zscores: dict[str, float],
    injury_risk_label: str = "low",
    injury_risk_score: float = 0.1,
    injury_adjusted_games: int = 70,
    consensus: ConsensusResult | None = None,
    rookie_flags: RookieFlags | None = None,
    playoff_value: float | None = 0.0,
) -> PlayerInputs:
    value = PlayerValue(
        per_game_zscores=per_game_zscores,
        per_game_value=sum(per_game_zscores.values()),
        availability_adjusted_zscores={},
        availability_adjusted_value=0.0,
        scarcity_score=0.0,
        punt_values={},
        position_scarcity_context={},
    )
    availability = Availability(
        raw_projected_games=float(injury_adjusted_games),
        injury_risk_score=injury_risk_score,
        injury_risk_label=injury_risk_label,
        injury_adjusted_games=injury_adjusted_games,
        availability_probability=injury_adjusted_games / 82,
        confidence=0.9,
    )
    playoff = PlayoffValue(
        expected_playoff_games=None, playoff_value=playoff_value, draft_value=0.0, regular_season_z=0.0, combined_value=0.0
    )
    return PlayerInputs(
        value=value,
        availability=availability,
        playoff=playoff,
        consensus=consensus,
        projection=_projection(),
        rookie_flags=rookie_flags,
    )


def _result(
    *,
    final_rank: int,
    model_rank: int,
    contributions: dict[str, float],
    disagreement: Disagreement,
) -> CompositeResult:
    # only the fields explain() actually reads need real values; component_scores
    # and confidence aren't consulted by explain(), so they're filled with placeholders
    return CompositeResult(
        component_scores={},
        component_contributions=contributions,
        model_score=0.0,
        model_rank=model_rank,
        final_score=0.0,
        final_rank=final_rank,
        confidence=0,
        confidence_band="LOW",
        disagreement=disagreement,
    )


def _all_text(explanation) -> str:
    return " ".join(explanation.strengths) + " " + " ".join(explanation.risks) + " " + explanation.paragraph


def test_full_fixture_player_strengths_risks_and_paragraph(settings: Settings) -> None:
    # fg_pct/pts/ast clear the elite bar (>=1.5z), tpm/stl clear "strong"
    # (0.5<=z<1.5, stl drops off the top-4 cut), ft_pct/tov are weak (<=-1.0z)
    zscores = {
        "fg_pct": 2.1,
        "ft_pct": -1.4,
        "tpm": 0.8,
        "pts": 1.6,
        "reb": 0.3,
        "ast": 1.9,
        "stl": 0.6,
        "blk": -0.2,
        "tov": -1.8,
    }
    consensus = ConsensusResult(consensus_rank=25.0, sources_used=3, rank_variance=50.0, per_source={})
    inputs = _inputs(
        per_game_zscores=zscores,
        injury_risk_label="moderate",
        injury_risk_score=0.42,
        injury_adjusted_games=64,
        consensus=consensus,
        playoff_value=1.2,
    )
    contributions = {
        "per_game": 0.42,
        "availability_adjusted": 0.10,
        "expected_games": 0.05,
        "role_usage": 0.03,
        "playoff_schedule": 0.02,
        "consensus": -0.01,
        "team_environment": 0.01,
        "category_scarcity": 0.01,
    }
    result = _result(
        final_rank=6,
        model_rank=5,
        contributions=contributions,
        disagreement=Disagreement(rank_difference=20.0, flag="model_loves"),
    )

    explanation = explain("Test Star", inputs, result, settings)

    assert explanation.strengths == [
        "elite FG% (+2.1z)",
        "elite AST (+1.9z)",
        "elite PTS (+1.6z)",
        "strong 3PM (+0.8z)",
    ]
    assert explanation.risks == [
        "moderate/high injury risk (score 0.42, 64 projected games)",
        "weak TO (-1.8z)",
        "weak FT% (-1.4z)",
    ]
    assert explanation.paragraph == (
        "Test Star ranks #6 overall, projected for 64 games, driven mainly by "
        "per-game production and availability-adjusted value, with FG% as the top category (+2.1z). "
        "Model is 20 spots higher than consensus (#5 vs #25), driven by per-game production. "
        "Favorable Week 19-21 schedule."
    )

    # test hygiene: no unresolved template artifacts anywhere in the output
    text = _all_text(explanation)
    assert "None" not in text
    assert "{" not in text


def test_paragraph_held_back_by_negative_component_never_listed_as_driver(settings: Settings) -> None:
    # H5: team_environment (-0.30) is the 2nd-largest |contribution| after
    # per_game (0.40) -- it must show up as "held back by", never as a driver
    inputs = _inputs(per_game_zscores={})
    contributions = {
        "per_game": 0.40,
        "availability_adjusted": 0.05,
        "expected_games": 0.02,
        "role_usage": 0.01,
        "playoff_schedule": 0.00,
        "consensus": 0.00,
        "team_environment": -0.30,
        "category_scarcity": 0.00,
    }
    result = _result(
        final_rank=50,
        model_rank=50,
        contributions=contributions,
        disagreement=Disagreement(rank_difference=None, flag="no_consensus"),
    )

    explanation = explain("Pace Drag Player", inputs, result, settings)

    assert "held back by team pace" in explanation.paragraph
    assert "driven mainly by per-game production" in explanation.paragraph
    # never phrased as a driver
    assert "driven mainly by team pace" not in explanation.paragraph
    assert "and team pace" not in explanation.paragraph


def test_paragraph_notes_unpublished_playoff_schedule(settings: Settings) -> None:
    inputs = _inputs(per_game_zscores={}, playoff_value=None)
    result = _result(
        final_rank=10,
        model_rank=10,
        contributions={"per_game": 0.4},
        disagreement=Disagreement(rank_difference=None, flag="no_consensus"),
    )

    explanation = explain("Rookie Guard", inputs, result, settings)

    # season string is threaded from settings.season, not a bare literal
    assert f"{settings.season} playoff schedule not yet published" in explanation.paragraph
    assert "playoff weight redistributed" in explanation.paragraph


def test_paragraph_notes_light_playoff_schedule(settings: Settings) -> None:
    inputs = _inputs(per_game_zscores={}, playoff_value=-1.3)
    result = _result(
        final_rank=40,
        model_rank=40,
        contributions={"per_game": 0.2},
        disagreement=Disagreement(rank_difference=None, flag="no_consensus"),
    )

    explanation = explain("Bench Wing", inputs, result, settings)

    assert "Light Week 19-21 schedule." in explanation.paragraph


def test_playoff_window_text_reflects_settings(tmp_path: Path) -> None:
    # proves the week range is genuinely threaded through settings, not a
    # literal: a modified playoff_window must change the emitted text
    data = json.loads(SHIPPED_SETTINGS.read_text())
    data["playoff_window"] = {"start_week": 1, "end_week": 3}
    # the primary playoff_window must stay one of the candidate options
    data["candidate_playoff_windows"] = [[1, 3]]
    modified_path = tmp_path / "settings.json"
    modified_path.write_text(json.dumps(data))
    modified_settings = load_settings(modified_path)

    inputs = _inputs(per_game_zscores={}, playoff_value=1.5)
    result = _result(
        final_rank=1,
        model_rank=1,
        contributions={"per_game": 0.4},
        disagreement=Disagreement(rank_difference=None, flag="no_consensus"),
    )

    explanation = explain("Custom Window", inputs, result, modified_settings)

    assert "Favorable Week 1-3 schedule." in explanation.paragraph
    assert "Week 19-21" not in explanation.paragraph


def test_paragraph_omits_model_vs_consensus_when_no_significant_gap(settings: Settings) -> None:
    inputs = _inputs(per_game_zscores={}, consensus=ConsensusResult(15.0, 1, 2.0, {}))
    result = _result(
        final_rank=15,
        model_rank=14,
        contributions={"per_game": 0.3},
        disagreement=Disagreement(rank_difference=1.0, flag="none"),
    )

    explanation = explain("Steady Vet", inputs, result, settings)

    assert "vs #" not in explanation.paragraph


def test_rookie_high_uncertainty_and_limited_availability_risks(settings: Settings) -> None:
    consensus = ConsensusResult(consensus_rank=40.0, sources_used=4, rank_variance=200.0, per_source={})
    rookie_flags = RookieFlags(rookie=True, projection_confidence=0.55, role_uncertainty=0.6)
    inputs = _inputs(
        per_game_zscores={},
        injury_risk_label="low",
        injury_adjusted_games=45,
        consensus=consensus,
        rookie_flags=rookie_flags,
    )
    result = _result(
        final_rank=80,
        model_rank=60,
        contributions={"per_game": 0.1},
        disagreement=Disagreement(rank_difference=-20.0, flag="high_uncertainty"),
    )

    explanation = explain("Fresh Rookie", inputs, result, settings)

    assert explanation.risks == [
        "sources disagree widely (variance 200)",
        "rookie projection (confidence 0.55)",
        "limited availability (45 games)",
    ]
    text = _all_text(explanation)
    assert "None" not in text
    assert "{" not in text
