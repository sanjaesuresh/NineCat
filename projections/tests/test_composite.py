"""Tests for nineproj.value.composite: composite score, confidence, ranking (Task 13)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from nineproj.config import Settings, load_settings
from nineproj.models.availability import Availability
from nineproj.models.baseline import BaselineProjection
from nineproj.models.roles import AdjustedProjection, RoleChange
from nineproj.models.rookies import RookieFlags
from nineproj.value.composite import PlayerInputs, compute_composite
from nineproj.value.consensus import ConsensusResult
from nineproj.value.ninecat import PlayerValue
from nineproj.value.playoffs import PlayoffValue

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"

# 11-stat kwargs every AdjustedProjection/BaselineProjection needs; none of
# these individual stats feed compute_composite, so they're all zeroed out
_ZERO_STATS = dict(fgm=0.0, fga=0.0, ftm=0.0, fta=0.0, tpm=0.0, pts=0.0, reb=0.0, ast=0.0, stl=0.0, blk=0.0, tov=0.0)


@pytest.fixture()
def settings() -> Settings:
    return load_settings(SHIPPED_SETTINGS)


def _player_value(per_game_value: float, availability_adjusted_value: float, scarcity_score: float) -> PlayerValue:
    # only the 3 fields compute_composite reads are populated
    return PlayerValue(
        per_game_zscores={},
        per_game_value=per_game_value,
        availability_adjusted_zscores={},
        availability_adjusted_value=availability_adjusted_value,
        scarcity_score=scarcity_score,
        punt_values={},
        position_scarcity_context={},
    )


def _availability(injury_adjusted_games: int, confidence: float = 1.0) -> Availability:
    return Availability(
        raw_projected_games=float(injury_adjusted_games),
        injury_risk_score=0.1,
        injury_risk_label="low",
        injury_adjusted_games=injury_adjusted_games,
        availability_probability=injury_adjusted_games / 82,
        confidence=confidence,
    )


def _playoff(playoff_value: float | None) -> PlayoffValue:
    return PlayoffValue(
        expected_playoff_games=None,
        playoff_value=playoff_value,
        draft_value=0.0,
        regular_season_z=0.0,
        combined_value=0.0,
    )


def _projection(
    sample_size_score: float, role_score: float, role_confidence: float, pace_multiplier: float
) -> AdjustedProjection:
    baseline = BaselineProjection(
        minutes=30.0, games=None, sample_size_score=sample_size_score, seasons_used=["2025-26"], **_ZERO_STATS
    )
    role_change = RoleChange(
        direction="neutral", score=role_score, minutes_delta=0.0, usage_delta=0.0, confidence=role_confidence
    )
    return AdjustedProjection(
        minutes=30.0, pre_adjustment=baseline, role_change=role_change, pace_multiplier=pace_multiplier, **_ZERO_STATS
    )


def _consensus(consensus_rank: float, rank_variance: float = 0.0) -> ConsensusResult:
    return ConsensusResult(consensus_rank=consensus_rank, sources_used=1, rank_variance=rank_variance, per_source={})


def _pop_z(values: list[float]) -> list[float]:
    # independent reimplementation (not calling composite.py's own helper),
    # matching the population-z convention used across the value/ modules
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std = variance**0.5
    if std == 0:
        return [0.0] * n
    return [(v - mean) / std for v in values]


def test_composite_hand_computed_full_pool(settings: Settings) -> None:
    # A/B/C are evenly spaced on every population-normalized raw quantity, so
    # every one of those components lands on the same +-z3/0 pattern; role_usage,
    # playoff_schedule, and category_scarcity are already on their own comparable
    # scales and are used directly (not re-standardized).
    z3 = math.sqrt(1.5)
    pool = {
        "A": PlayerInputs(
            value=_player_value(per_game_value=1.0, availability_adjusted_value=1.0, scarcity_score=-1.0),
            availability=_availability(injury_adjusted_games=50),
            playoff=_playoff(playoff_value=-1.0),
            consensus=_consensus(consensus_rank=30.0),
            projection=_projection(sample_size_score=1.0, role_score=-0.5, role_confidence=0.9, pace_multiplier=0.95),
            rookie_flags=None,
        ),
        "B": PlayerInputs(
            value=_player_value(per_game_value=2.0, availability_adjusted_value=2.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=_consensus(consensus_rank=20.0),
            projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=1.0),
            rookie_flags=None,
        ),
        "C": PlayerInputs(
            value=_player_value(per_game_value=3.0, availability_adjusted_value=3.0, scarcity_score=1.0),
            availability=_availability(injury_adjusted_games=70),
            playoff=_playoff(playoff_value=1.0),
            consensus=_consensus(consensus_rank=10.0),
            projection=_projection(sample_size_score=1.0, role_score=0.5, role_confidence=0.9, pace_multiplier=1.05),
            rookie_flags=None,
        ),
    }

    results = compute_composite(pool, settings)
    w = settings.composite_weights

    # B2: team_environment is a bounded nudge (pace 0.95/1.0/1.05 with a 0.05
    # cap maps to exactly -1/0/+1), so it joins the direct-component group
    # below alongside role_usage/playoff_schedule/category_scarcity, not the
    # population-z group
    z_component_weight = w.per_game + w.availability_adjusted + w.expected_games + w.consensus
    direct_component = (
        w.role_usage * 0.5 + w.playoff_schedule * 1.0 + w.category_scarcity * 1.0 + w.team_environment * 1.0
    )
    expected_c_final = z_component_weight * z3 + direct_component
    expected_a_final = -expected_c_final

    assert results["A"].final_score == pytest.approx(expected_a_final, abs=1e-6)
    assert results["B"].final_score == pytest.approx(0.0, abs=1e-9)
    assert results["C"].final_score == pytest.approx(expected_c_final, abs=1e-6)
    assert results["A"].final_rank == 3
    assert results["B"].final_rank == 2
    assert results["C"].final_rank == 1

    # model_score excludes consensus entirely, renormalizing the other 7
    # weights over 0.95 instead of 1.0
    z_component_weight_no_c = w.per_game + w.availability_adjusted + w.expected_games
    expected_c_model = (z_component_weight_no_c * z3 + direct_component) / (1 - w.consensus)
    expected_a_model = -expected_c_model

    assert results["A"].model_score == pytest.approx(expected_a_model, abs=1e-6)
    assert results["B"].model_score == pytest.approx(0.0, abs=1e-9)
    assert results["C"].model_score == pytest.approx(expected_c_model, abs=1e-6)
    assert results["C"].model_rank == 1
    assert results["A"].model_rank == 3

    # component_scores/contributions expose the raw z's and the weighted terms
    assert results["C"].component_scores["per_game"] == pytest.approx(z3, abs=1e-6)
    assert results["C"].component_contributions["per_game"] == pytest.approx(w.per_game * z3, abs=1e-6)


def test_weight_shift_swaps_final_rank_between_two_players(settings: Settings, tmp_path: Path) -> None:
    # X leads on per_game but trails on consensus; Y is the mirror image.
    # Every other raw component is identical between them, so it cancels out.
    def _pool() -> dict[str, PlayerInputs]:
        return {
            "X": PlayerInputs(
                value=_player_value(per_game_value=2.0, availability_adjusted_value=5.0, scarcity_score=0.0),
                availability=_availability(injury_adjusted_games=60),
                playoff=_playoff(playoff_value=0.0),
                consensus=_consensus(consensus_rank=20.0),
                projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=1.0),
                rookie_flags=None,
            ),
            "Y": PlayerInputs(
                value=_player_value(per_game_value=1.0, availability_adjusted_value=5.0, scarcity_score=0.0),
                availability=_availability(injury_adjusted_games=60),
                playoff=_playoff(playoff_value=0.0),
                consensus=_consensus(consensus_rank=10.0),
                projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=1.0),
                rookie_flags=None,
            ),
        }

    default_results = compute_composite(_pool(), settings)
    w = settings.composite_weights
    # per_game z(X)=+1/z(Y)=-1, consensus_z(X)=-1/z(Y)=+1 (2-element pop z is always +-1)
    assert default_results["X"].final_score == pytest.approx(w.per_game - w.consensus, abs=1e-9)
    assert default_results["Y"].final_score == pytest.approx(-(w.per_game - w.consensus), abs=1e-9)
    assert default_results["X"].final_rank == 1
    assert default_results["Y"].final_rank == 2

    # swap per_game <-> consensus weights (still sums to 1.0) in a temp settings.json
    data = json.loads(SHIPPED_SETTINGS.read_text())
    old_per_game = data["composite_weights"]["per_game"]
    old_consensus = data["composite_weights"]["consensus"]
    data["composite_weights"]["per_game"] = old_consensus
    data["composite_weights"]["consensus"] = old_per_game
    swapped_path = tmp_path / "settings.json"
    swapped_path.write_text(json.dumps(data))
    swapped_settings = load_settings(swapped_path)

    swapped_results = compute_composite(_pool(), swapped_settings)
    sw = swapped_settings.composite_weights
    assert swapped_results["X"].final_score == pytest.approx(sw.per_game - sw.consensus, abs=1e-9)
    assert swapped_results["Y"].final_score == pytest.approx(-(sw.per_game - sw.consensus), abs=1e-9)
    # the weight shift flips who's ahead, exactly as hand math predicts
    assert swapped_results["Y"].final_rank == 1
    assert swapped_results["X"].final_rank == 2


def test_composite_weights_not_summing_to_one_still_rejected_by_loader(tmp_path: Path) -> None:
    # composite.py has no weight-sum logic of its own -- this invariant is
    # entirely the config loader's job (nineproj.config), asserted here too
    # since compute_composite's renormalization silently assumes it holds
    data = json.loads(SHIPPED_SETTINGS.read_text())
    data["composite_weights"]["per_game"] = 0.99
    bad_path = tmp_path / "settings.json"
    bad_path.write_text(json.dumps(data))

    with pytest.raises(Exception, match="sum to 1.0|composite_weights"):
        load_settings(bad_path)


def test_no_consensus_imputes_hand_computed_z_against_real_population(settings: Settings) -> None:
    # H4: real population is {P_mid: rank 10, P_hi: rank 30} -> mean=20, std=10.
    # rank_for_imputation = max_consensus_list_length(50) + imputation_penalty(10) = 60
    # imputed_z = -(60 - 20) / 10 = -4.0
    pool = {
        "P_none": PlayerInputs(
            value=_player_value(per_game_value=1.0, availability_adjusted_value=1.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=None,
            projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=1.0),
            rookie_flags=None,
        ),
        "P_mid": PlayerInputs(
            value=_player_value(per_game_value=2.0, availability_adjusted_value=2.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=_consensus(consensus_rank=10.0),
            projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=1.0),
            rookie_flags=None,
        ),
        "P_hi": PlayerInputs(
            value=_player_value(per_game_value=3.0, availability_adjusted_value=3.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=_consensus(consensus_rank=30.0),
            projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=1.0),
            rookie_flags=None,
        ),
    }

    results = compute_composite(pool, settings, max_consensus_list_length=50)

    assert results["P_none"].component_scores["consensus"] == pytest.approx(-4.0, abs=1e-9)
    # no-consensus semantics (flag, rank_difference) are unaffected by imputation
    assert results["P_none"].disagreement.flag == "no_consensus"
    assert results["P_none"].disagreement.rank_difference is None


def test_no_consensus_final_score_strictly_below_mid_consensus_player(settings: Settings) -> None:
    # P_none and P_mid are otherwise identical (same per_game/availability/
    # scarcity/role/pace/games -- every population-z component ties between
    # them since the raw value is literally the same); P_hi only exists to
    # give the pool a real 2-point consensus population to impute against.
    # P_none's imputed rank (60) is far worse than P_mid's real rank (10), so
    # final_score must strictly favor P_mid once consensus is no longer
    # silently redistributed away for P_none.
    def _twin(consensus: ConsensusResult | None) -> PlayerInputs:
        return PlayerInputs(
            value=_player_value(per_game_value=1.0, availability_adjusted_value=1.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=consensus,
            projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=1.0),
            rookie_flags=None,
        )

    pool = {
        "P_none": _twin(None),
        "P_mid": _twin(_consensus(consensus_rank=10.0)),
        "P_hi": PlayerInputs(
            value=_player_value(per_game_value=3.0, availability_adjusted_value=3.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=_consensus(consensus_rank=30.0),
            projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=1.0),
            rookie_flags=None,
        ),
    }

    results = compute_composite(pool, settings, max_consensus_list_length=50)

    assert results["P_none"].final_score < results["P_mid"].final_score


def test_model_rank_excludes_consensus_and_can_diverge_from_final_rank(settings: Settings) -> None:
    # every non-consensus raw quantity ties between M and N except a tiny
    # role_usage nudge; consensus alone (weight 0.05) is large enough to flip
    # the overall order once it's blended into final_score
    pool = {
        "M": PlayerInputs(
            value=_player_value(per_game_value=5.0, availability_adjusted_value=5.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=_consensus(consensus_rank=20.0),
            projection=_projection(sample_size_score=1.0, role_score=0.001, role_confidence=0.9, pace_multiplier=1.0),
            rookie_flags=None,
        ),
        "N": PlayerInputs(
            value=_player_value(per_game_value=5.0, availability_adjusted_value=5.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=_consensus(consensus_rank=10.0),
            projection=_projection(sample_size_score=1.0, role_score=-0.001, role_confidence=0.9, pace_multiplier=1.0),
            rookie_flags=None,
        ),
    }

    results = compute_composite(pool, settings)

    # model_score (no consensus): the tiny role_usage nudge alone decides it
    assert results["M"].model_rank == 1
    assert results["N"].model_rank == 2

    # final_score (with consensus): consensus dominates the tiny role gap and flips it
    assert results["N"].final_rank == 1
    assert results["M"].final_rank == 2


def test_confidence_stable_veteran_exceeds_rookie(settings: Settings) -> None:
    # rank_variance=16 -> sqrt(16)/40 = 0.1 -> agreement_part = 0.9 exactly
    veteran_pool = {
        "V": PlayerInputs(
            value=_player_value(per_game_value=1.0, availability_adjusted_value=1.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=75, confidence=0.9),
            playoff=_playoff(playoff_value=0.0),
            consensus=_consensus(consensus_rank=5.0, rank_variance=16.0),
            projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.7, pace_multiplier=1.0),
            rookie_flags=None,
        )
    }
    rookie_pool = {
        "R": PlayerInputs(
            value=_player_value(per_game_value=1.0, availability_adjusted_value=1.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60, confidence=0.5),
            playoff=_playoff(playoff_value=0.0),
            consensus=None,
            projection=_projection(sample_size_score=0.0, role_score=0.0, role_confidence=0.5, pace_multiplier=1.0),
            rookie_flags=RookieFlags(rookie=True, projection_confidence=0.5, role_uncertainty=0.5),
        )
    }

    veteran = compute_composite(veteran_pool, settings)["V"]
    rookie = compute_composite(rookie_pool, settings)["R"]

    # raw = .3*1.0 + .25*0.9 + .25*0.7 + .2*0.9 = 0.88
    assert veteran.confidence == 88
    assert veteran.confidence_band == "HIGH"
    # raw = .3*0.5 + .25*0.5 + .25*0.5 + .2*0.5 = 0.5 (no consensus -> agreement_part=0.5)
    assert rookie.confidence == 50
    assert rookie.confidence_band == "LOW"
    assert veteran.confidence > rookie.confidence


def _team_environment_pool(pace_multipliers: dict[str, float], settings: Settings) -> dict[str, PlayerInputs]:
    return {
        pid: PlayerInputs(
            value=_player_value(per_game_value=1.0, availability_adjusted_value=1.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=_consensus(consensus_rank=10.0),
            projection=_projection(
                sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=pace
            ),
            rookie_flags=None,
        )
        for pid, pace in pace_multipliers.items()
    }


def test_team_environment_bounded_nudge_pace_at_cap_and_neutral(settings: Settings) -> None:
    # B2: pace 1.05 with a 0.05 cap -> exactly +1.0; pace 1.0 -> exactly 0.0
    pool = _team_environment_pool({"UP": 1.05, "FLAT": 1.0, "DOWN": 0.95}, settings)
    results = compute_composite(pool, settings)

    assert results["UP"].component_scores["team_environment"] == pytest.approx(1.0, abs=1e-9)
    assert results["FLAT"].component_scores["team_environment"] == pytest.approx(0.0, abs=1e-9)
    assert results["DOWN"].component_scores["team_environment"] == pytest.approx(-1.0, abs=1e-9)


def test_team_environment_contribution_never_exceeds_its_own_weight(settings: Settings) -> None:
    # a lone pace-changer (CHANGER) in an otherwise-static pool must never
    # pull more than settings.composite_weights.team_environment -- the B2
    # bug (z-score laundering a +-5% cap into +-6 sigma) let this dominate
    # per_game; CHANGER also leads on per_game_value so this is a realistic
    # "elite scorer whose team also changed pace" shape, not a degenerate one
    def _player(per_game_value: float, pace: float) -> PlayerInputs:
        return PlayerInputs(
            value=_player_value(per_game_value=per_game_value, availability_adjusted_value=1.0, scarcity_score=0.0),
            availability=_availability(injury_adjusted_games=60),
            playoff=_playoff(playoff_value=0.0),
            consensus=_consensus(consensus_rank=10.0),
            projection=_projection(sample_size_score=1.0, role_score=0.0, role_confidence=0.9, pace_multiplier=pace),
            rookie_flags=None,
        )

    pool = {
        "CHANGER": _player(per_game_value=10.0, pace=1.05),
        "STATIC_A": _player(per_game_value=0.0, pace=1.0),
        "STATIC_B": _player(per_game_value=0.0, pace=1.0),
    }
    results = compute_composite(pool, settings)
    w = settings.composite_weights

    contribution = results["CHANGER"].component_contributions["team_environment"]
    assert abs(contribution) <= w.team_environment + 1e-9
    assert abs(contribution) < abs(results["CHANGER"].component_contributions["per_game"])
