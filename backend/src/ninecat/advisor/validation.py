"""Response validation, including the shortlist-integrity guard (plan B4).

Pure: takes the raw response body and the request it answered, returns a
validated result or raises. No network, no clock, no database.

The guard is the point of this module. A1 promises the model can reorder and
explain but can never invent or drop a player, and a promise made only in the
prompt is not enforcement -- a plausible-sounding explanation for a player the
engine never shortlisted would launder a recommendation the engine never made.
Request-level output schemas cannot express this: they can require a list of
{item_key, reasoning}, but not WHICH keys are legal. So it lives here.
"""

from __future__ import annotations

import json

from ninecat.advisor.types import (
    REASON_MALFORMED,
    REASON_SHORTLIST_MISMATCH,
    AdvisorRequest,
    AdvisorResult,
    ItemExplanation,
)


class AdvisorRejected(Exception):
    """A response came back but is unusable. Carries a structured reason token
    so the caller degrades to deterministic output with an honest cause."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_response(raw_text: str, request: AdvisorRequest, model: str) -> AdvisorResult:
    try:
        payload = json.loads(raw_text)
    except ValueError as exc:
        raise AdvisorRejected(REASON_MALFORMED) from exc

    if not isinstance(payload, dict):
        raise AdvisorRejected(REASON_MALFORMED)

    summary = payload.get("summary")
    ranked_raw = payload.get("ranked")
    if not isinstance(summary, str) or not isinstance(ranked_raw, list):
        raise AdvisorRejected(REASON_MALFORMED)

    explanations: list[ItemExplanation] = []
    for item in ranked_raw:
        if not isinstance(item, dict):
            raise AdvisorRejected(REASON_MALFORMED)
        item_key = item.get("item_key")
        reasoning = item.get("reasoning")
        if not isinstance(item_key, str) or not isinstance(reasoning, str):
            raise AdvisorRejected(REASON_MALFORMED)
        # an entry with no prose is worse than no entry: the UI would render a
        # blank attributed explanation, which reads as a bug rather than as
        # "we have nothing to add"
        if not reasoning.strip():
            raise AdvisorRejected(REASON_MALFORMED)
        explanations.append(
            ItemExplanation(item_key=item_key, reasoning=reasoning.strip())
        )

    _assert_shortlist_intact(explanations, request)

    summary = summary.strip()
    if not summary:
        raise AdvisorRejected(REASON_MALFORMED)

    return AdvisorResult(model=model, summary=summary, ranked=tuple(explanations))


def _assert_shortlist_intact(
    explanations: list[ItemExplanation], request: AdvisorRequest
) -> None:
    """Membership must match the shortlist exactly -- same keys, same count,
    each exactly once. Order is free; that is the whole permitted freedom.

    Compared as sorted lists rather than sets so a duplicated key is caught too:
    two entries for one player and none for another has matching set membership
    but is still a dropped player.
    """
    returned = sorted(e.item_key for e in explanations)
    expected = sorted(request.item_keys())
    if returned != expected:
        raise AdvisorRejected(REASON_SHORTLIST_MISMATCH)
