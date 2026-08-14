"""Tests for the settings loader (nineproj.config)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nineproj.config import load_settings

SHIPPED_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


def test_shipped_settings_playoff_window() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    assert settings.playoff_window.start_week == 19
    assert settings.playoff_window.end_week == 21


def test_shipped_settings_candidate_playoff_windows() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    assert settings.candidate_playoff_windows == (
        (17, 19), (18, 20), (19, 21), (20, 22), (21, 23), (22, 24),
    )


def test_candidate_playoff_windows_bad_range_raises(tmp_path: Path) -> None:
    data = json.loads(SHIPPED_SETTINGS.read_text())
    data["candidate_playoff_windows"] = [[19, 21], [23, 20]]
    bad_path = tmp_path / "settings.json"
    bad_path.write_text(json.dumps(data))

    with pytest.raises(Exception, match="candidate_playoff_windows"):
        load_settings(bad_path)


def test_playoff_window_not_in_candidates_raises(tmp_path: Path) -> None:
    data = json.loads(SHIPPED_SETTINGS.read_text())
    # 19-21 (the primary window) is missing from this candidate list
    data["candidate_playoff_windows"] = [[17, 19], [18, 20], [20, 22]]
    bad_path = tmp_path / "settings.json"
    bad_path.write_text(json.dumps(data))

    with pytest.raises(Exception, match="candidate_playoff_windows"):
        load_settings(bad_path)


def test_shipped_settings_value_split() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    assert settings.value_split.regular_season == pytest.approx(0.75)
    assert settings.value_split.playoff == pytest.approx(0.25)


def test_shipped_settings_composite_weights_sum_to_one() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    total = sum(settings.composite_weights.model_dump().values())
    assert total == pytest.approx(1.0, abs=1e-9)


def test_shipped_settings_is_frozen() -> None:
    settings = load_settings(SHIPPED_SETTINGS)
    # pydantic frozen models raise on attribute assignment
    with pytest.raises(Exception):
        settings.season = "2027-28"  # type: ignore[misc]


def test_unknown_key_raises_clear_error(tmp_path: Path) -> None:
    data = json.loads(SHIPPED_SETTINGS.read_text())
    data["totally_unknown_field"] = "surprise"
    bad_path = tmp_path / "settings.json"
    bad_path.write_text(json.dumps(data))

    with pytest.raises(Exception, match="totally_unknown_field"):
        load_settings(bad_path)


def test_composite_weights_not_summing_to_one_raises(tmp_path: Path) -> None:
    data = json.loads(SHIPPED_SETTINGS.read_text())
    data["composite_weights"]["per_game"] = 0.99  # breaks the sum-to-1.0 invariant
    bad_path = tmp_path / "settings.json"
    bad_path.write_text(json.dumps(data))

    with pytest.raises(Exception, match="sum to 1.0|composite_weights"):
        load_settings(bad_path)


def test_value_split_not_summing_to_one_raises(tmp_path: Path) -> None:
    data = json.loads(SHIPPED_SETTINGS.read_text())
    data["value_split"] = {"regular_season": 0.9, "playoff": 0.25}
    bad_path = tmp_path / "settings.json"
    bad_path.write_text(json.dumps(data))

    with pytest.raises(Exception, match="sum to 1.0|value_split"):
        load_settings(bad_path)


def test_negative_composite_weight_raises_even_if_sum_is_one(tmp_path: Path) -> None:
    data = json.loads(SHIPPED_SETTINGS.read_text())
    # sum still equals 1.0 (0.50 - 0.10 + 0.30 + 0.10 + 0.05*4 = 1.0), but a
    # negative weight must still be rejected by the non-negativity guard.
    data["composite_weights"]["per_game"] = 0.50
    data["composite_weights"]["availability_adjusted"] = -0.10
    data["composite_weights"]["expected_games"] = 0.30
    bad_path = tmp_path / "settings.json"
    bad_path.write_text(json.dumps(data))

    with pytest.raises(Exception, match="non-negative"):
        load_settings(bad_path)


def test_playoff_window_start_after_end_raises(tmp_path: Path) -> None:
    data = json.loads(SHIPPED_SETTINGS.read_text())
    data["playoff_window"] = {"start_week": 21, "end_week": 19}
    bad_path = tmp_path / "settings.json"
    bad_path.write_text(json.dumps(data))

    with pytest.raises(Exception, match="start_week|playoff_window"):
        load_settings(bad_path)
