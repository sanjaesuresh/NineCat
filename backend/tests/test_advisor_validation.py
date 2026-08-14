"""Response validation and the shortlist-integrity guard (plan A1/B4).

The guard is the single most important thing in this sub-project: a
plausible-sounding explanation for a player the engine never shortlisted would
launder a recommendation the engine never made.
"""

import json

import pytest

from ninecat.advisor.types import (
    REASON_MALFORMED,
    REASON_SHORTLIST_MISMATCH,
    FEATURE_DRAFT,
    AdvisorRequest,
    ShortlistPlayer,
)
from ninecat.advisor.validation import AdvisorRejected, validate_response

MODEL = "claude-opus-5"


def _request(*player_keys: str) -> AdvisorRequest:
    return AdvisorRequest(
        feature=FEATURE_DRAFT,
        situation="pick 1 overall",
        shortlist=tuple(
            ShortlistPlayer(player_key=key, name=f"Player {key}", position="C")
            for key in player_keys
        ),
    )


def _body(*pairs: tuple[str, str], summary: str = "Take the guard.") -> str:
    return json.dumps(
        {"summary": summary, "ranked": [{"player_key": k, "reasoning": r} for k, r in pairs]}
    )


def test_accepts_a_wellformed_response():
    request = _request("1", "2")
    body = _body(("1", "Best all-round value."), ("2", "Close second."))

    result = validate_response(body, request, MODEL)

    assert result.model == MODEL
    assert result.summary == "Take the guard."
    assert [e.player_key for e in result.ranked] == ["1", "2"]
    assert result.ranked[0].reasoning == "Best all-round value."


def test_accepts_a_response_that_reorders_within_the_shortlist():
    # reordering is the one freedom the model has, and it must be allowed
    request = _request("1", "2", "3")
    body = _body(("3", "Actually the best fit."), ("1", "Still fine."), ("2", "Third."))

    result = validate_response(body, request, MODEL)

    assert [e.player_key for e in result.ranked] == ["3", "1", "2"]


def test_rejects_a_player_that_was_not_on_the_shortlist():
    # THE A1 guarantee: the model may not smuggle in a player the engine never
    # put forward, no matter how good the prose is
    request = _request("1", "2")
    body = _body(("1", "Good."), ("2", "Also good."), ("999", "Sleeper nobody is talking about."))

    with pytest.raises(AdvisorRejected) as exc:
        validate_response(body, request, MODEL)

    assert exc.value.reason == REASON_SHORTLIST_MISMATCH


def test_rejects_a_substituted_player_even_when_the_count_matches():
    # same length, so a naive len() check would pass this
    request = _request("1", "2")
    body = _body(("1", "Good."), ("999", "Not on the shortlist."))

    with pytest.raises(AdvisorRejected) as exc:
        validate_response(body, request, MODEL)

    assert exc.value.reason == REASON_SHORTLIST_MISMATCH


def test_rejects_a_dropped_player():
    request = _request("1", "2", "3")
    body = _body(("1", "Good."), ("2", "Fine."))

    with pytest.raises(AdvisorRejected) as exc:
        validate_response(body, request, MODEL)

    assert exc.value.reason == REASON_SHORTLIST_MISMATCH


def test_rejects_a_duplicated_player():
    # set membership would match here; a duplicate necessarily means some other
    # shortlist player went unexplained, which is a dropped player
    request = _request("1", "2")
    body = _body(("1", "Good."), ("1", "Good again."))

    with pytest.raises(AdvisorRejected) as exc:
        validate_response(body, request, MODEL)

    assert exc.value.reason == REASON_SHORTLIST_MISMATCH


@pytest.mark.parametrize(
    "body",
    [
        "not json at all",
        "",
        json.dumps(["a", "list"]),
        json.dumps({"summary": "x"}),
        json.dumps({"ranked": []}),
        json.dumps({"summary": 7, "ranked": []}),
        json.dumps({"summary": "x", "ranked": "not a list"}),
        json.dumps({"summary": "x", "ranked": ["not an object"]}),
        json.dumps({"summary": "x", "ranked": [{"player_key": 1, "reasoning": "y"}]}),
        json.dumps({"summary": "x", "ranked": [{"player_key": "1"}]}),
    ],
    ids=[
        "not-json", "empty", "top-level-list", "missing-ranked", "missing-summary",
        "summary-not-string", "ranked-not-list", "item-not-object", "key-not-string",
        "missing-reasoning",
    ],
)
def test_rejects_malformed_bodies(body):
    with pytest.raises(AdvisorRejected) as exc:
        validate_response(body, _request("1"), MODEL)

    assert exc.value.reason == REASON_MALFORMED


def test_rejects_blank_reasoning():
    # a blank attributed explanation renders as a bug, not as "nothing to add"
    with pytest.raises(AdvisorRejected) as exc:
        validate_response(_body(("1", "   ")), _request("1"), MODEL)

    assert exc.value.reason == REASON_MALFORMED


def test_rejects_blank_summary():
    with pytest.raises(AdvisorRejected) as exc:
        validate_response(_body(("1", "Fine."), summary="  "), _request("1"), MODEL)

    assert exc.value.reason == REASON_MALFORMED


def test_strips_surrounding_whitespace():
    result = validate_response(
        _body(("1", "  Best value.  "), summary="  Take him.  "), _request("1"), MODEL
    )

    assert result.summary == "Take him."
    assert result.ranked[0].reasoning == "Best value."
