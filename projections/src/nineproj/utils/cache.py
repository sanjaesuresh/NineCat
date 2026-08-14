"""On-disk JSON cache for nba_api (and other slow/rate-limited) live fetches.

Every live-data fetcher in nineproj.data goes through cached_fetch instead of
calling its endpoint directly: it persists results with a retrieval timestamp
(so a warmed run needs no network at all) and enforces a minimum gap between
live calls so a full-universe run doesn't hammer stats.nba.com. A stale cache
still beats a hard failure, so a live fetch that keeps failing falls back to
whatever was last cached instead of taking down the whole pipeline run.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# projections/data/raw/, resolved from this file's location (not cwd) so
# cached_fetch behaves the same no matter where a script/test runs from;
# every test passes its own tmp_path cache_dir instead, so this constant is
# never actually written to during the suite
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = _PROJECT_ROOT / "data" / "raw"

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 2.0
_MIN_CALL_INTERVAL_SECONDS = 0.6

# last time a live fetch actually ran (monotonic clock), shared across every
# cached_fetch call in the process -- a burst of different keys/endpoints
# still respects the one rate limit stats.nba.com effectively imposes
_last_live_call_at: float = 0.0

_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_filename(key: str) -> str:
    return _SAFE_KEY_RE.sub("_", key) + ".json"


def _read_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        # a corrupt/truncated cache file is treated as "no cache" rather than a hard error
        return None


def _write_cache(path: Path, data: Any, endpoint: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "data": data,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
    }
    path.write_text(json.dumps(envelope))


def _is_fresh(envelope: dict[str, Any], ttl_hours: float) -> bool:
    fetched_at = datetime.fromisoformat(envelope["fetched_at"])
    age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
    return age_hours < ttl_hours


def _throttle(sleep: Callable[[float], None]) -> None:
    """Wait out the minimum gap since the last live call anywhere in the process."""
    global _last_live_call_at
    elapsed = time.monotonic() - _last_live_call_at
    if elapsed < _MIN_CALL_INTERVAL_SECONDS:
        sleep(_MIN_CALL_INTERVAL_SECONDS - elapsed)
    _last_live_call_at = time.monotonic()


def cached_fetch(
    key: str,
    ttl_hours: float,
    fetch_fn: Callable[[], Any],
    *,
    cache_dir: Path | None = None,
    endpoint: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_stale: Callable[[], None] | None = None,
    serve_expired: bool = False,
) -> Any:
    """Return fetch_fn()'s result, cached on disk under `key` for `ttl_hours`.

    Fresh cache on disk -> served directly, fetch_fn is never called. Expired
    or missing cache -> fetch_fn is retried up to 3 times with exponential
    backoff (2s, 4s; `sleep` is injectable so tests never actually wait), each
    attempt throttled to a 600ms minimum gap since the last live call. If every
    attempt fails: an existing cache file (even an expired one) is served
    instead, `on_stale` is invoked, and a warning is logged; with no cache file
    at all, the last fetch exception propagates.

    `serve_expired=True` (H2, --offline mode): an on-disk cache file is served
    immediately regardless of staleness -- fetch_fn is never called, so there's
    no retry/backoff cost at all. Only when no cache file exists is fetch_fn
    called, and then only once (no retries, no backoff sleeps) -- offline mode
    already forbids live fetches, so retrying a fetcher that's guaranteed to
    raise just burns minutes on sleeps for nothing.

    `cache_dir` defaults to DEFAULT_CACHE_DIR (projections/data/raw/) but every
    caller that isn't hitting a real endpoint (i.e. every test) must pass its
    own tmp_path here instead.
    """
    resolved_dir = cache_dir or DEFAULT_CACHE_DIR
    path = resolved_dir / _safe_filename(key)
    cached = _read_cache(path)

    if cached is not None and _is_fresh(cached, ttl_hours):
        return cached["data"]

    if serve_expired:
        if cached is not None:
            # visible-but-not-noisy: an expired file being served silently
            # would hide a genuinely stale offline run from the log entirely
            logger.warning(
                "serving expired cache for key=%s (fetched_at=%s)", key, cached.get("fetched_at")
            )
            return cached["data"]
        return fetch_fn()

    last_exc: Exception | None = None
    backoff = _BACKOFF_BASE_SECONDS
    for attempt in range(_MAX_ATTEMPTS):
        _throttle(sleep)
        try:
            data = fetch_fn()
        except Exception as exc:  # noqa: BLE001 - any failure here retries or falls back to stale
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                sleep(backoff)
                backoff *= 2
            continue
        _write_cache(path, data, endpoint)
        return data

    if cached is not None:
        logger.warning(
            "live fetch failed for key=%s (endpoint=%s); serving stale cache from %s",
            key,
            endpoint,
            cached.get("fetched_at"),
        )
        if on_stale is not None:
            on_stale()
        return cached["data"]

    assert last_exc is not None  # unreachable: the loop always sets it before falling through
    raise last_exc
