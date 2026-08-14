"""Tests for the consensus ranking model and disagreement flags (Task 12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nineproj.config import Settings, load_settings
from nineproj.research.schema import ConsensusList, SourceRef
from nineproj.value.consensus import consensus_ranks, disagreement

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


@pytest.fixture()
def settings() -> Settings:
    return load_settings(SHIPPED_SETTINGS)


def _source(type_: str, quality_tier: str, name: str = "Test Wire") -> SourceRef:
    return SourceRef(
        source=name,
        url="https://example.com/wire/x",
        retrieved="2026-08-01",
        season_label="2026-27",
        quality_tier=quality_tier,
        type=type_,
    )


def _list(type_: str, quality_tier: str, players: list[str], name: str) -> ConsensusList:
    return ConsensusList(source=_source(type_, quality_tier, name), players=players)


def test_consensus_rank_hand_weighted_two_sources(settings: Settings) -> None:
    # X: expert_rank/high -> w=.25*.85=.2125, ranks P1 #2
    list_x = _list("expert_rank", "high", ["Other A", "P1"], "Source X")
    # Y: adp/medium -> w=.10*.5=.05, ranks P1 #6
    list_y = _list("adp", "medium", ["o1", "o2", "o3", "o4", "o5", "P1"], "Source Y")

    results = consensus_ranks([list_x, list_y], ["P1"], settings)
    result = results["p1"]

    expected = (0.2125 * 2 + 0.05 * 6) / (0.2125 + 0.05)
    assert result.consensus_rank == pytest.approx(expected, abs=1e-6)
    assert result.consensus_rank == pytest.approx(2.761905, abs=1e-6)
    assert result.sources_used == 2


def test_missing_player_imputed_and_flagged(settings: Settings) -> None:
    players_a = ["a0", "a1", "a2", "a3", "P2", "a5", "a6", "a7", "a8", "a9"]
    players_b = ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8", "b9"]
    list_a = _list("projection", "medium_high", players_a, "Source A")
    list_b = _list("community_rank", "medium", players_b, "Source B")

    results = consensus_ranks([list_a, list_b], ["P2"], settings)
    result = results["p2"]

    # real rank in A is index 4 -> rank 5; B omits P2, so imputed = 10 (len) + 10 (penalty) = 20
    assert result.per_source["Source A"] == {"rank": 5, "imputed": False}
    assert result.per_source["Source B"] == {"rank": 20, "imputed": True}
    # imputed source does not count toward sources_used, but its rank still
    # feeds the weighted average
    assert result.sources_used == 1
    w_a = settings.consensus.source_type_weights.projection * settings.consensus.quality_tier_weights.medium_high
    w_b = settings.consensus.source_type_weights.community_rank * settings.consensus.quality_tier_weights.medium
    expected = (w_a * 5 + w_b * 20) / (w_a + w_b)
    assert result.consensus_rank == pytest.approx(expected, abs=1e-9)


def test_player_absent_from_every_list_gets_none_result(settings: Settings) -> None:
    list_a = _list("news", "low", ["Someone Else"], "Source A")
    results = consensus_ranks([list_a], ["Nobody Here"], settings)
    result = results["nobody here"]

    assert result.consensus_rank is None
    assert result.sources_used == 0
    assert result.rank_variance is None
    assert result.per_source == {}


def test_player_absent_from_both_of_multiple_lists_gets_none_result(settings: Settings) -> None:
    # distinct from the single-list absent case above: with >1 list in play,
    # "absent from every list" must still collapse to None/no_consensus, not
    # accidentally get imputed against one of the lists it's missing from
    list_a = _list("news", "low", ["Someone Else"], "Source A")
    list_b = _list("adp", "medium", ["Another Person"], "Source B")

    results = consensus_ranks([list_a, list_b], ["Nobody Here"], settings)
    result = results["nobody here"]

    assert result.consensus_rank is None
    assert result.sources_used == 0
    assert result.rank_variance is None
    assert result.per_source == {}


def test_alias_fallback_matches_cam_cameron_nickname(settings: Settings) -> None:
    # coordinator follow-up: "Cameron Johnson" (requested) vs list's "Cam
    # Johnson" -- same last name, "cam" is a >=2-char prefix of "cameron" --
    # must resolve as a real (non-imputed) match, not eat the imputation dock
    list_a = _list("expert_rank", "high", ["Other A", "Cam Johnson", "Other B"], "Source A")

    results = consensus_ranks([list_a], ["Cameron Johnson"], settings)
    result = results["cameron johnson"]

    assert result.consensus_rank == pytest.approx(2.0)
    assert result.sources_used == 1
    assert result.per_source["Source A"] == {"rank": 2, "imputed": False}


def test_alias_fallback_matches_lu_luguentz_nickname(settings: Settings) -> None:
    list_a = _list("adp", "medium", ["Other A", "Lu Dort"], "Source A")

    results = consensus_ranks([list_a], ["Luguentz Dort"], settings)
    result = results["luguentz dort"]

    assert result.consensus_rank == pytest.approx(2.0)
    assert result.sources_used == 1
    assert result.per_source["Source A"] == {"rank": 2, "imputed": False}


def test_alias_fallback_ambiguous_two_candidates_falls_through_to_imputed(settings: Settings) -> None:
    # "Cam Johnson" vs a list with BOTH "Cameron Johnson" and "Camden
    # Johnson" -- both share last name "johnson" and both first names are
    # prefixed by "cam" -- 2 candidates, not 1, so list_a must fall through
    # to the normal imputed-rank path, not guess. list_b gives an unambiguous
    # exact match so the player isn't globally unmentioned (which would
    # otherwise collapse straight to the all-None/empty-per_source result,
    # masking whether the ambiguous list specifically resolved correctly).
    list_a = _list("expert_rank", "high", ["Cameron Johnson", "Camden Johnson"], "Source A")
    list_b = _list("adp", "medium", ["Cam Johnson"], "Source B")

    results = consensus_ranks([list_a, list_b], ["Cam Johnson"], settings)
    result = results["cam johnson"]

    assert result.per_source["Source A"] == {
        "rank": len(list_a.players) + settings.consensus.imputation_penalty,
        "imputed": True,
    }
    assert result.per_source["Source B"] == {"rank": 1, "imputed": False}
    assert result.sources_used == 1


def test_alias_fallback_unrelated_names_do_not_match(settings: Settings) -> None:
    list_a = _list("expert_rank", "high", ["Tyler Johnson", "Someone Else"], "Source A")

    results = consensus_ranks([list_a], ["Cameron Johnson"], settings)
    result = results["cameron johnson"]

    # last names differ ("johnson" only via a different first name entirely,
    # not a nickname of "cameron") -- unmentioned everywhere collapses to the
    # same all-None result as any other never-mentioned player
    assert result.consensus_rank is None
    assert result.sources_used == 0
    assert result.per_source == {}


def test_alias_fallback_does_not_steal_an_exact_match_target(settings: Settings) -> None:
    # both "Cameron Johnson" and "Cam Johnson" are real, distinct requested
    # players; the list only has "Cam Johnson" exactly -- that entry is
    # claimed by its own exact match and must not also be handed to
    # "Cameron Johnson" as a fallback (if it were stolen, "cameron johnson"
    # would get a real, non-None rank here instead of the all-None result)
    list_a = _list("expert_rank", "high", ["Cam Johnson"], "Source A")

    results = consensus_ranks([list_a], ["Cameron Johnson", "Cam Johnson"], settings)

    assert results["cam johnson"].per_source["Source A"] == {"rank": 1, "imputed": False}
    assert results["cameron johnson"].consensus_rank is None
    assert results["cameron johnson"].per_source == {}


def test_rank_variance_zero_when_real_sources_agree(settings: Settings) -> None:
    list_a = _list("expert_rank", "high", ["o1", "o2", "P1"], "Source A")
    list_b = _list("adp", "low", ["o1", "o2", "P1"], "Source B")

    results = consensus_ranks([list_a, list_b], ["P1"], settings)
    assert results["p1"].rank_variance == pytest.approx(0.0)


def test_rank_variance_hand_computed_when_real_sources_disagree(settings: Settings) -> None:
    # X: statistical_model/very_high -> w=.3*1.0=.3, ranks P1 #1
    list_x = _list("statistical_model", "very_high", ["P1"], "Source X")
    # Y: projection/medium -> w=.2*.5=.1, ranks P1 #11 (needs 11 slots)
    list_y = _list("projection", "medium", [f"o{i}" for i in range(10)] + ["P1"], "Source Y")

    results = consensus_ranks([list_x, list_y], ["P1"], settings)
    result = results["p1"]

    # mean = (.3*1 + .1*11) / .4 = 3.5; var = (.3*(1-3.5)^2 + .1*(11-3.5)^2) / .4 = 18.75
    assert result.rank_variance == pytest.approx(18.75, abs=1e-9)


def test_disagreement_model_loves(settings: Settings) -> None:
    result = disagreement(5, 25.0, rank_variance=1.0, settings=settings)
    assert result.rank_difference == pytest.approx(20.0)
    assert result.flag == "model_loves"


def test_disagreement_model_fades(settings: Settings) -> None:
    result = disagreement(40, 20.0, rank_variance=1.0, settings=settings)
    assert result.rank_difference == pytest.approx(-20.0)
    assert result.flag == "model_fades"


def test_disagreement_high_uncertainty_trumps_love_and_fade(settings: Settings) -> None:
    # 30-spot gap alone would be model_loves, but variance 200 > 144 threshold wins
    result = disagreement(20, 50.0, rank_variance=200.0, settings=settings)
    assert result.flag == "high_uncertainty"


def test_disagreement_no_consensus(settings: Settings) -> None:
    result = disagreement(10, None, rank_variance=None, settings=settings)
    assert result.rank_difference is None
    assert result.flag == "no_consensus"


def test_disagreement_boundary_exactly_at_threshold(settings: Settings) -> None:
    # threshold is 15; a difference of exactly 15 must already flag model_loves
    result = disagreement(100, 115.0, rank_variance=1.0, settings=settings)
    assert result.rank_difference == pytest.approx(15.0)
    assert result.flag == "model_loves"


def test_name_normalization_matches_across_variants(settings: Settings) -> None:
    list_a = _list("expert_rank", "high", ["Other A", "Test Star Jr."], "Source A")
    results = consensus_ranks([list_a], ["test star"], settings)

    assert "test star" in results
    result = results["test star"]
    assert result.consensus_rank == pytest.approx(2.0)
    assert result.sources_used == 1
