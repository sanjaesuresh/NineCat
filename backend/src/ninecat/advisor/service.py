"""Orchestration: cache lookup -> API call -> validation -> cache store.

This is the only function a feature endpoint calls. It never raises for an
advisor problem; every failure path returns an AdvisorOutcome carrying a reason
token, so the caller keeps its deterministic engine result and simply says
explanations are off (plan A2/A5).
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.orm import Session

from ninecat.advisor.cache import cache_key, read_cached, write_cached
from ninecat.advisor.client import AdvisorClient, AdvisorUnavailable, AnthropicAdvisorClient
from ninecat.advisor.prompt import build_prompt
from ninecat.advisor.types import (
    REASON_EMPTY_SHORTLIST,
    REASON_NOT_CONFIGURED,
    RESPONSE_SCHEMA,
    AdvisorOutcome,
    AdvisorRequest,
)
from ninecat.advisor.validation import AdvisorRejected, validate_response
from ninecat.config import Settings


def build_advisor_client(settings: Settings) -> AdvisorClient | None:
    """The real client, or None when no key is configured.

    None is not an error condition -- it is the mode the whole test suite and
    every key-less deployment runs in.
    """
    if not settings.explanations_available:
        return None
    return _cached_client(settings.anthropic_api_key, settings.anthropic_model)


@lru_cache(maxsize=1)
def _cached_client(api_key: str, model: str) -> AnthropicAdvisorClient:
    # one client (and one underlying connection pool) per process rather than
    # one per request. The key only ever comes from Settings, which already
    # holds it in memory, so caching on it adds no new exposure.
    return AnthropicAdvisorClient(api_key, model)


def explain(
    db: Session,
    request: AdvisorRequest,
    *,
    client: AdvisorClient | None,
    model: str,
) -> AdvisorOutcome:
    """Explain a shortlist, or say why we can't. Never raises for advisor reasons.

    `model` is passed explicitly rather than read from the client because it is
    part of the cache key: the cache must be consulted before we know (or need)
    whether a client exists at all, and two models are two different answers.
    """
    if not request.shortlist:
        # nothing to rank; calling the API would burn a request to be told so
        return AdvisorOutcome(result=None, reason=REASON_EMPTY_SHORTLIST)

    key = cache_key(request, model)
    cached = read_cached(db, key)
    if cached is not None:
        # a cache hit serves even with no key configured: the answer is already
        # paid for, contains no identifiers, and is the same question
        return AdvisorOutcome(result=cached, reason=None, cached=True)

    if client is None:
        return AdvisorOutcome(result=None, reason=REASON_NOT_CONFIGURED)

    system, user = build_prompt(request)
    try:
        completion = client.complete(system=system, user=user, schema=RESPONSE_SCHEMA)
    except AdvisorUnavailable as exc:
        return AdvisorOutcome(result=None, reason=exc.reason)

    try:
        result = validate_response(completion.text, request, completion.model)
    except AdvisorRejected as exc:
        # a rejected response is deliberately NOT cached -- caching it would
        # pin a bad answer to this question until the TTL expired
        return AdvisorOutcome(result=None, reason=exc.reason)

    write_cached(db, key, request, result, completion)
    return AdvisorOutcome(result=result, reason=None)
