"""Tests for the research evidence schema and store (nineproj.research)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nineproj.config import load_settings
from nineproj.research.schema import InjuryNote, SourceRef
from nineproj.research.store import load_store

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "research"
INVALID_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "research_invalid"
MALFORMED_SYNTAX_FIXTURES = (
    Path(__file__).resolve().parent / "fixtures" / "research_invalid" / "malformed_syntax"
)
BAD_QUALITY_TIER_FIXTURES = (
    Path(__file__).resolve().parent / "fixtures" / "research_invalid_bad_quality_tier"
)
SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


@pytest.fixture()
def settings():
    return load_settings(SHIPPED_SETTINGS)


def test_consensus_list_loaded(settings) -> None:
    store = load_store(FIXTURES, settings)
    assert len(store.consensus_lists) == 1
    assert store.consensus_lists[0].players[0] == "Test Star A"


def test_lookup_by_normalized_name_ignores_stray_punctuation(settings) -> None:
    store = load_store(FIXTURES, settings)
    # "test star a." (stray trailing period) must still resolve to "Test Star A"
    transactions = store.transactions_for("test star a.")
    assert len(transactions) == 1
    assert transactions[0].player == "Test Star A"


def test_transactions_for_returns_all_matches(settings) -> None:
    store = load_store(FIXTURES, settings)
    assert len(store.transactions_for("Test Star B")) == 1
    assert store.transactions_for("Nobody Here") == []


def test_injuries_for(settings) -> None:
    store = load_store(FIXTURES, settings)
    injuries = store.injuries_for("Test Star A")
    assert len(injuries) == 1
    assert injuries[0].chronic is False


def test_roles_for(settings) -> None:
    store = load_store(FIXTURES, settings)
    roles = store.roles_for("Test Star C")
    assert len(roles) == 1
    assert roles[0].direction == "positive"


def test_rookie_for_returns_single_item_or_none(settings) -> None:
    store = load_store(FIXTURES, settings)
    rookie = store.rookie_for("Test Rookie Q")
    assert rookie is not None
    assert rookie.team == "Test Town Titans"
    assert store.rookie_for("Nobody Here") is None


def test_sentiment_for(settings) -> None:
    store = load_store(FIXTURES, settings)
    sentiment = store.sentiment_for("Test Star E")
    assert len(sentiment) == 1
    assert sentiment[0].stance == "breakout"


def test_item_weight_matches_settings_quality_tier_weight(settings) -> None:
    store = load_store(FIXTURES, settings)
    injury = store.injuries_for("Test Star A")[0]
    # fixture's source.quality_tier is "high"
    assert injury.weight == pytest.approx(settings.consensus.quality_tier_weights.high)

    transactions = store.transactions_for("Test Star A")
    # fixture's source.quality_tier is "very_high"
    assert transactions[0].weight == pytest.approx(
        settings.consensus.quality_tier_weights.very_high
    )


def test_invalid_fixture_raises_value_error_naming_the_file(settings) -> None:
    with pytest.raises(ValueError, match="injuries_missing_url.json"):
        load_store(INVALID_FIXTURES, settings)


def test_bad_quality_tier_raises_value_error_naming_the_file(settings) -> None:
    # quality_tier is a fixed Literal (config.py's 6 tier keys) -- an
    # off-list value must fail loudly at load time, not silently pass through
    with pytest.raises(ValueError, match="roles_bad_quality_tier.json"):
        load_store(BAD_QUALITY_TIER_FIXTURES, settings)


def test_malformed_json_syntax_raises_value_error_naming_the_file(settings) -> None:
    # a syntactically broken file (trailing comma) must still name the
    # offending path, not bubble up a bare JSONDecodeError with no context
    with pytest.raises(ValueError, match="bad_trailing_comma.json"):
        load_store(MALFORMED_SYNTAX_FIXTURES, settings)


def test_directly_constructed_item_has_weight_none() -> None:
    # weight is only meaningful once load_store attaches the real tier
    # weight; a model built by hand (e.g. in another test) must not silently
    # look zero-weighted
    source = SourceRef(
        source="Test Wire",
        url="https://example.com/wire/x",
        retrieved="2026-08-01",
        season_label="2026-27",
        quality_tier="high",
        type="news",
    )
    injury = InjuryNote(
        player="Test Star Z", status="fine", chronic=False, source=source
    )
    assert injury.weight is None


def test_source_ref_rejects_garbage_url() -> None:
    with pytest.raises(Exception, match="url"):
        SourceRef(
            source="Test Wire",
            url="httpgarbage-not-a-real-url",
            retrieved="2026-08-01",
            season_label="2026-27",
            quality_tier="high",
            type="news",
        )
