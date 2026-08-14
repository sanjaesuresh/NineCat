"""Advisor response cache: key derivation plus read/write against advisor_cache.

The API's own prompt caching does nothing for us -- it only caches prefixes
above a minimum size, and our prompts (a shortlist and a few stat lines) are far
below it. This table is therefore not an optimisation layered on top of API
caching, it is the only caching there is. Do not remove it thinking the API
covers it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.advisor.client import AdvisorCompletion
from ninecat.advisor.types import (
    PROMPT_VERSION,
    AdvisorRequest,
    AdvisorResult,
    ItemExplanation,
)
from ninecat.models.advisor import AdvisorCache

# entries never go "stale" in the usual sense -- everything that could change
# the answer is already in the key -- but a long-lived row would keep serving
# text written by an older prompt if PROMPT_VERSION were ever left un-bumped by
# mistake. This is the backstop for that, not a freshness requirement.
ADVISOR_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


def cache_key(request: AdvisorRequest, model: str) -> str:
    """sha256 over the normalized request. Must be stable across processes.

    `sort_keys=True` is doing the load-bearing work: it orders every mapping
    recursively, so no dict or set iteration order can reach the hash. This
    project has been bitten by hash-order dependence before, so the test asserts
    stability across separate interpreter processes, not just two calls in one.

    Shortlist ORDER is preserved (a list, not a sorted set) on purpose: the
    prompt presents the shortlist in engine order, so a different engine order
    is a genuinely different question and must miss the cache.
    """
    canonical = {
        "prompt_version": PROMPT_VERSION,
        "feature": request.feature,
        "model": model,
        "situation": request.situation,
        "context": dict(request.context),
        "shortlist": [
            {
                "item_key": item.item_key,
                "label": item.label,
                "detail": item.detail,
                "metrics": dict(item.metrics),
                "tags": list(item.tags),
            }
            for item in request.shortlist
        ],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_cached(db: Session, key: str) -> AdvisorResult | None:
    row = db.execute(
        select(AdvisorCache).where(AdvisorCache.request_hash == key)
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.created_at + timedelta(seconds=ADVISOR_CACHE_TTL_SECONDS) <= datetime.now(
        timezone.utc
    ):
        return None
    return _result_from_payload(row.payload)


def write_cached(
    db: Session,
    key: str,
    request: AdvisorRequest,
    result: AdvisorResult,
    completion: AdvisorCompletion,
) -> None:
    """Store a validated result. The payload carries no user identifiers, which
    is what makes the row safe to share across users (plan B6)."""
    payload = {
        "model": result.model,
        "summary": result.summary,
        "ranked": [
            {"item_key": e.item_key, "reasoning": e.reasoning} for e in result.ranked
        ],
    }
    # atomic upsert: a select-then-insert would let two concurrent cold-cache
    # calls for the same question both insert and trip the unique constraint
    stmt = pg_insert(AdvisorCache).values(
        request_hash=key,
        feature=request.feature,
        model=result.model,
        payload=payload,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        created_at=datetime.now(timezone.utc),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["request_hash"],
        set_={
            "payload": stmt.excluded.payload,
            "input_tokens": stmt.excluded.input_tokens,
            "output_tokens": stmt.excluded.output_tokens,
            "created_at": stmt.excluded.created_at,
        },
    )
    db.execute(stmt)
    db.flush()


def _result_from_payload(payload: dict) -> AdvisorResult:
    return AdvisorResult(
        model=payload["model"],
        summary=payload["summary"],
        ranked=tuple(
            ItemExplanation(item_key=e["item_key"], reasoning=e["reasoning"])
            for e in payload["ranked"]
        ),
    )
