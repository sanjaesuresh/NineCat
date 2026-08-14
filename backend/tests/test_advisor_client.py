"""The advisor client seam: soft failure, one branch per typed SDK exception.

Plan A5 requires every failure mode to degrade softly and be tested
individually, not collapsed into one generic "it failed" case -- so each typed
exception gets its own assertion here. Nothing in this file touches the network:
the SDK client is injected.
"""

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from ninecat.advisor.client import (
    ADVISOR_EFFORT,
    ADVISOR_MAX_RETRIES,
    ADVISOR_TIMEOUT_SECONDS,
    AdvisorUnavailable,
    AnthropicAdvisorClient,
)
from ninecat.advisor.types import (
    REASON_API_ERROR,
    REASON_AUTH,
    REASON_CONNECTION,
    REASON_MALFORMED,
    REASON_OVERLOADED,
    REASON_RATE_LIMITED,
    REASON_REFUSED,
    REASON_TIMEOUT,
    RESPONSE_SCHEMA,
)

_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status: int) -> Exception:
    return cls("boom", response=httpx.Response(status, request=_REQUEST), body=None)


class _StubMessages:
    def __init__(self, *, response=None, error=None):
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _StubSdk:
    def __init__(self, *, response=None, error=None):
        self.messages = _StubMessages(response=response, error=error)


def _response(
    *, text="{}", stop_reason="end_turn", model="claude-opus-5", thinking_block=False
):
    content = []
    if thinking_block:
        # thinking is on, so thinking blocks share the content list with text
        content.append(SimpleNamespace(type="thinking", thinking="internal"))
    content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        content=content,
        model=model,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=1200, output_tokens=340),
    )


def _client(sdk) -> AnthropicAdvisorClient:
    return AnthropicAdvisorClient("unused-in-tests", "claude-opus-5", sdk_client=sdk)


def test_returns_text_and_usage_on_success():
    sdk = _StubSdk(response=_response(text='{"summary":"ok","ranked":[]}'))

    completion = _client(sdk).complete(system="sys", user="usr", schema=RESPONSE_SCHEMA)

    assert completion.text == '{"summary":"ok","ranked":[]}'
    assert completion.model == "claude-opus-5"
    assert (completion.input_tokens, completion.output_tokens) == (1200, 340)


def test_ignores_thinking_blocks_when_reading_the_answer():
    # thinking is deliberately left on (disabling it risks internal tags
    # leaking into visible output), so the reader must skip those blocks
    sdk = _StubSdk(response=_response(text='{"summary":"ok"}', thinking_block=True))

    completion = _client(sdk).complete(system="sys", user="usr", schema=RESPONSE_SCHEMA)

    assert completion.text == '{"summary":"ok"}'
    assert "internal" not in completion.text


def test_sends_the_schema_and_the_low_effort_setting():
    sdk = _StubSdk(response=_response())

    _client(sdk).complete(system="sys", user="usr", schema=RESPONSE_SCHEMA)

    sent = sdk.messages.calls[0]
    assert sent["model"] == "claude-opus-5"
    assert sent["system"] == "sys"
    assert sent["messages"] == [{"role": "user", "content": "usr"}]
    assert sent["output_config"]["effort"] == ADVISOR_EFFORT
    assert sent["output_config"]["format"] == {
        "type": "json_schema",
        "schema": RESPONSE_SCHEMA,
    }
    # thinking is never configured explicitly: on the current Opus it is on by
    # default, and disabling it is the documented tag-leak risk
    assert "thinking" not in sent


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (anthropic.APITimeoutError(request=_REQUEST), REASON_TIMEOUT),
        (anthropic.APIConnectionError(request=_REQUEST), REASON_CONNECTION),
        (_status_error(anthropic.RateLimitError, 429), REASON_RATE_LIMITED),
        (_status_error(anthropic.AuthenticationError, 401), REASON_AUTH),
        (_status_error(anthropic.PermissionDeniedError, 403), REASON_AUTH),
        (_status_error(anthropic.OverloadedError, 529), REASON_OVERLOADED),
        (_status_error(anthropic.InternalServerError, 500), REASON_API_ERROR),
        (_status_error(anthropic.BadRequestError, 400), REASON_API_ERROR),
        (_status_error(anthropic.NotFoundError, 404), REASON_API_ERROR),
    ],
    ids=[
        "timeout", "connection", "rate-limit", "auth", "permission",
        "overloaded", "server-error", "bad-request", "not-found",
    ],
)
def test_each_typed_sdk_error_maps_to_its_own_reason(error, reason):
    sdk = _StubSdk(error=error)

    with pytest.raises(AdvisorUnavailable) as exc:
        _client(sdk).complete(system="sys", user="usr", schema=RESPONSE_SCHEMA)

    assert exc.value.reason == reason


def test_timeout_is_not_swallowed_into_the_connection_branch():
    # APITimeoutError subclasses APIConnectionError, so an isinstance chain in
    # the wrong order would silently collapse the two
    sdk = _StubSdk(error=anthropic.APITimeoutError(request=_REQUEST))

    with pytest.raises(AdvisorUnavailable) as exc:
        _client(sdk).complete(system="sys", user="usr", schema=RESPONSE_SCHEMA)

    assert exc.value.reason == REASON_TIMEOUT
    assert exc.value.reason != REASON_CONNECTION


def test_unexpected_exception_still_degrades_softly():
    # a bug in the SDK, or anything else we did not anticipate, must not turn a
    # recommendation page into a 500
    sdk = _StubSdk(error=RuntimeError("something new"))

    with pytest.raises(AdvisorUnavailable) as exc:
        _client(sdk).complete(system="sys", user="usr", schema=RESPONSE_SCHEMA)

    assert exc.value.reason == REASON_API_ERROR


def test_refusal_is_detected_before_reading_content():
    # safety classifiers decline with a normal 200 and an empty/partial body
    sdk = _StubSdk(response=_response(text="", stop_reason="refusal"))

    with pytest.raises(AdvisorUnavailable) as exc:
        _client(sdk).complete(system="sys", user="usr", schema=RESPONSE_SCHEMA)

    assert exc.value.reason == REASON_REFUSED


def test_truncated_response_is_treated_as_malformed():
    sdk = _StubSdk(response=_response(text='{"summary":"ok","ran', stop_reason="max_tokens"))

    with pytest.raises(AdvisorUnavailable) as exc:
        _client(sdk).complete(system="sys", user="usr", schema=RESPONSE_SCHEMA)

    assert exc.value.reason == REASON_MALFORMED


def test_failure_never_carries_the_underlying_exception_or_request():
    # the SDK exception holds the request, whose body is the whole prompt;
    # chaining it would put prompt contents into any logged traceback (plan B8)
    sdk = _StubSdk(error=_status_error(anthropic.BadRequestError, 400))

    with pytest.raises(AdvisorUnavailable) as exc:
        _client(sdk).complete(system="sys", user="usr", schema=RESPONSE_SCHEMA)

    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None or exc.value.__suppress_context__


def test_wait_is_bounded_by_a_single_attempt():
    # retries are off on purpose: the caller already degrades gracefully, so
    # the advisor trades retry coverage for a hard latency bound (plan B7)
    assert ADVISOR_MAX_RETRIES == 0
    assert ADVISOR_TIMEOUT_SECONDS <= 30.0


def test_does_not_log_prompt_contents(caplog):
    sdk = _StubSdk(response=_response())

    with caplog.at_level("INFO"):
        _client(sdk).complete(
            system="SYSTEM-PROMPT-MARKER", user="USER-PROMPT-MARKER", schema=RESPONSE_SCHEMA
        )

    logged = caplog.text
    assert "SYSTEM-PROMPT-MARKER" not in logged
    assert "USER-PROMPT-MARKER" not in logged
    # token usage IS logged -- that is the observability half of plan B8
    assert "input_tokens=1200" in logged
    assert "output_tokens=340" in logged
