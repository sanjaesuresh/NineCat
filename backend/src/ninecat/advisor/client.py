"""The single choke point for every Anthropic API call the app makes.

The advisor takes its client as a constructor argument rather than building one
(plan B1) -- the same seam the Yahoo gateway and the nba_api fetchers already
use. Every test passes a fake, so no test can reach the network even by
accident, and the no-key path stays the default everywhere.

Failure is soft (plan A5): each typed SDK exception maps to a structured reason
token and an AdvisorUnavailable, never to a 500. A recommendation page must
never fail because an explanation service is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import anthropic

from ninecat.advisor.types import (
    REASON_API_ERROR,
    REASON_AUTH,
    REASON_CONNECTION,
    REASON_MALFORMED,
    REASON_OVERLOADED,
    REASON_RATE_LIMITED,
    REASON_REFUSED,
    REASON_TIMEOUT,
)

logger = logging.getLogger(__name__)

# per-attempt wall clock. Deliberately tight: the advisor sits in the request
# path of a page the user is waiting on, and its output is optional, so a slow
# explanation must lose rather than make the whole page slow (plan B7).
ADVISOR_TIMEOUT_SECONDS = 20.0

# the SDK defaults to 2 retries, which would multiply the bound above to ~60s of
# wall clock on a bad day. A retry buys little here -- the caller already
# degrades gracefully and the answer is cached once it succeeds -- so the
# advisor trades retry coverage for a hard, single-attempt latency bound.
ADVISOR_MAX_RETRIES = 0

# a ceiling, not a target: it caps thinking plus response text together, and
# unused headroom costs nothing. Sized so a shortlist's worth of short
# explanations can never be truncated mid-JSON by the cap itself.
ADVISOR_MAX_TOKENS = 16000

# thinking is left ON at the lowest effort rather than disabled. Disabling it
# has a documented failure mode -- internal tags leaking into visible output --
# which is exactly the wrong risk for a feature whose entire job is user-facing
# prose. Effort is the cost/latency lever instead.
ADVISOR_EFFORT = "low"


class AdvisorUnavailable(Exception):
    """The call did not produce a usable response. Carries a structured reason
    token; never carries an SDK exception, a request body, or the key."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AdvisorCompletion:
    """What the seam returns: raw text plus the usage worth logging."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int


class AdvisorClient(Protocol):
    """The seam. Tests implement this directly; nothing else may call the SDK."""

    def complete(self, *, system: str, user: str, schema: dict) -> AdvisorCompletion: ...


class AnthropicAdvisorClient:
    """AdvisorClient backed by the real Anthropic API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = ADVISOR_TIMEOUT_SECONDS,
        max_retries: int = ADVISOR_MAX_RETRIES,
        sdk_client: anthropic.Anthropic | None = None,
    ):
        self._model = model
        # sdk_client is the test seam for THIS class specifically (the seam for
        # everything above it is AdvisorClient itself) -- it lets the
        # exception-mapping and response-reading code below be exercised
        # against every typed SDK error without a network call, exactly like
        # YahooGateway's injectable http_client
        self._client = sdk_client or anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )

    def complete(self, *, system: str, user: str, schema: dict) -> AdvisorCompletion:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=ADVISOR_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                # the schema constrains the response at the request level; our
                # own validation still runs on the way out (see validation.py)
                output_config={
                    "effort": ADVISOR_EFFORT,
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except Exception as exc:
            # swallow rather than chain: the SDK exception carries the request,
            # and chaining would put the whole prompt into any traceback that
            # gets logged downstream. Only the class name is recorded.
            reason = _reason_for(exc)
            logger.warning("advisor call failed: %s (%s)", reason, type(exc).__name__)
            raise AdvisorUnavailable(reason) from None

        # safety classifiers can decline a request with a normal 200 and an
        # empty/partial body -- check the stop reason before reading content
        if response.stop_reason == "refusal":
            logger.warning("advisor call refused by safety classifiers")
            raise AdvisorUnavailable(REASON_REFUSED)
        if response.stop_reason == "max_tokens":
            # the body is truncated, so any JSON in it is unparseable anyway
            logger.warning("advisor response truncated at max_tokens")
            raise AdvisorUnavailable(REASON_MALFORMED)

        # thinking blocks share the content list with text blocks; only text
        # carries the structured answer
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        # token usage is logged for observability; prompt contents never are (B8)
        logger.info(
            "advisor call ok: model=%s input_tokens=%d output_tokens=%d",
            response.model,
            input_tokens,
            output_tokens,
        )
        return AdvisorCompletion(
            text=text,
            model=response.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _reason_for(exc: Exception) -> str:
    """Map one typed SDK exception to one structured reason token.

    Ordered most-specific-first, and deliberately not a bare catch-all: A5's
    soft-failure requirement is per failure mode, and each branch is tested
    against its own exception type rather than one generic "it failed" case.
    APITimeoutError subclasses APIConnectionError, so it must come first.
    """
    if isinstance(exc, anthropic.APITimeoutError):
        return REASON_TIMEOUT
    if isinstance(exc, anthropic.APIConnectionError):
        return REASON_CONNECTION
    if isinstance(exc, anthropic.RateLimitError):
        return REASON_RATE_LIMITED
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return REASON_AUTH
    # OverloadedError (529) is a sibling of InternalServerError, not a subclass
    # of it -- both hang off APIStatusError -- so ordering between these two
    # doesn't matter, but neither may be folded into the other
    if isinstance(exc, anthropic.OverloadedError):
        return REASON_OVERLOADED
    return REASON_API_ERROR
