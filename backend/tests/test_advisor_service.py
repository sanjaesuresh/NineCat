"""The advisor service: cache -> call -> validate -> cache, and every path that
degrades to deterministic output instead of raising (plan A2/A5).
"""

import json

import anthropic
import httpx
from sqlalchemy import func, select

from ninecat.advisor.cache import cache_key
from ninecat.advisor.client import (
    AdvisorCompletion,
    AdvisorUnavailable,
    AnthropicAdvisorClient,
)
from ninecat.advisor.service import build_advisor_client, explain
from ninecat.advisor.types import (
    REASON_EMPTY_SHORTLIST,
    REASON_MALFORMED,
    REASON_NOT_CONFIGURED,
    REASON_RATE_LIMITED,
    REASON_SHORTLIST_MISMATCH,
    REASON_TIMEOUT,
    FEATURE_DRAFT,
    AdvisorRequest,
    ShortlistItem,
)
from ninecat.config import Settings, get_settings
from ninecat.models.advisor import AdvisorCache

MODEL = "claude-opus-5"

REQUIRED_ENV = {
    "yahoo_client_id": "x",
    "yahoo_client_secret": "x",
    "yahoo_redirect_uri": "https://example.test/cb",
    "token_encryption_key": "x",
    "session_secret": "x",
    "database_url": "postgresql+psycopg://postgres:postgres@localhost:54329/postgres",
}


class _FakeAdvisorClient:
    """The AdvisorClient seam, implemented directly. No network, ever."""

    def __init__(self, *, text: str | None = None, error: Exception | None = None):
        self._text = text
        self._error = error
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str, schema: dict) -> AdvisorCompletion:
        self.calls.append((system, user))
        if self._error is not None:
            raise self._error
        return AdvisorCompletion(
            text=self._text, model=MODEL, input_tokens=1200, output_tokens=340
        )


def _request(*keys: str) -> AdvisorRequest:
    return AdvisorRequest(
        feature=FEATURE_DRAFT,
        situation="pick 12 overall in a 12-team 9-cat league",
        context={"punting": "ft_pct"},
        shortlist=tuple(
            ShortlistItem(item_key=k, label=f"Player {k}", detail="C") for k in keys
        ),
    )


def _good_body(*keys: str) -> str:
    return json.dumps(
        {
            "summary": "Take the first one.",
            "ranked": [{"item_key": k, "reasoning": f"Reason for {k}."} for k in keys],
        }
    )


def _cached_row_count(db) -> int:
    return db.execute(select(func.count()).select_from(AdvisorCache)).scalar_one()


# --- happy path ---


def test_returns_a_validated_result_and_caches_it(db_session):
    client = _FakeAdvisorClient(text=_good_body("2", "1"))

    outcome = explain(db_session, _request("1", "2"), client=client, model=MODEL)

    assert outcome.reason is None
    assert outcome.cached is False
    assert [e.item_key for e in outcome.result.ranked] == ["2", "1"]
    assert _cached_row_count(db_session) == 1


def test_second_identical_call_is_served_from_cache(db_session):
    client = _FakeAdvisorClient(text=_good_body("1", "2"))
    explain(db_session, _request("1", "2"), client=client, model=MODEL)

    outcome = explain(db_session, _request("1", "2"), client=client, model=MODEL)

    assert outcome.cached is True
    assert outcome.result is not None
    # the point of the cache: the same question does not re-bill
    assert len(client.calls) == 1


def test_a_changed_shortlist_calls_again(db_session):
    client = _FakeAdvisorClient(text=_good_body("1", "2"))
    explain(db_session, _request("1", "2"), client=client, model=MODEL)

    client_two = _FakeAdvisorClient(text=_good_body("1", "2", "3"))
    explain(db_session, _request("1", "2", "3"), client=client_two, model=MODEL)

    assert len(client_two.calls) == 1
    assert _cached_row_count(db_session) == 2


# --- no-key mode (the default path for the whole suite and for CI) ---


def test_no_client_returns_the_not_configured_reason(db_session):
    outcome = explain(db_session, _request("1", "2"), client=None, model=MODEL)

    assert outcome.result is None
    assert outcome.reason == REASON_NOT_CONFIGURED
    assert _cached_row_count(db_session) == 0


def test_a_cache_hit_is_served_even_with_no_client(db_session):
    # the answer is already paid for and contains no identifiers, so losing the
    # key must not throw it away
    client = _FakeAdvisorClient(text=_good_body("1", "2"))
    explain(db_session, _request("1", "2"), client=client, model=MODEL)

    outcome = explain(db_session, _request("1", "2"), client=None, model=MODEL)

    assert outcome.cached is True
    assert outcome.result is not None


def test_empty_shortlist_never_calls_the_api(db_session):
    client = _FakeAdvisorClient(text=_good_body())

    outcome = explain(db_session, _request(), client=client, model=MODEL)

    assert outcome.reason == REASON_EMPTY_SHORTLIST
    assert client.calls == []


# --- soft failure ---


def test_a_client_failure_degrades_softly(db_session):
    client = _FakeAdvisorClient(error=AdvisorUnavailable(REASON_RATE_LIMITED))

    outcome = explain(db_session, _request("1", "2"), client=client, model=MODEL)

    assert outcome.result is None
    assert outcome.reason == REASON_RATE_LIMITED
    assert _cached_row_count(db_session) == 0


def test_a_malformed_response_degrades_softly_and_is_not_cached(db_session):
    client = _FakeAdvisorClient(text="this is not json")

    outcome = explain(db_session, _request("1", "2"), client=client, model=MODEL)

    assert outcome.reason == REASON_MALFORMED
    # caching a rejected answer would pin it to this question until the TTL
    assert _cached_row_count(db_session) == 0


def test_a_smuggled_player_degrades_softly_and_is_not_cached(db_session):
    # the A1 guarantee end to end: the engine's shortlist wins, in code
    client = _FakeAdvisorClient(text=_good_body("1", "2", "999"))

    outcome = explain(db_session, _request("1", "2"), client=client, model=MODEL)

    assert outcome.result is None
    assert outcome.reason == REASON_SHORTLIST_MISMATCH
    assert _cached_row_count(db_session) == 0


def test_a_rejected_response_is_retried_on_the_next_call(db_session):
    # nothing was cached, so a transient bad answer does not poison the question
    bad = _FakeAdvisorClient(text="not json")
    explain(db_session, _request("1", "2"), client=bad, model=MODEL)

    good = _FakeAdvisorClient(text=_good_body("1", "2"))
    outcome = explain(db_session, _request("1", "2"), client=good, model=MODEL)

    assert outcome.result is not None
    assert len(good.calls) == 1


def test_a_real_sdk_timeout_degrades_softly_through_both_layers(db_session):
    """End to end across the client seam with the real AnthropicAdvisorClient:
    an SDK exception must become a reason token, never escape as an error."""

    class _TimingOutSdk:
        class messages:  # noqa: N801 - mirrors the SDK's attribute layout
            @staticmethod
            def create(**_kwargs):
                raise anthropic.APITimeoutError(
                    request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
                )

    client = AnthropicAdvisorClient("unused-in-tests", MODEL, sdk_client=_TimingOutSdk())

    outcome = explain(db_session, _request("1", "2"), client=client, model=MODEL)

    assert outcome.result is None
    assert outcome.reason == REASON_TIMEOUT


# --- client construction ---


def test_build_advisor_client_returns_none_without_a_key():
    get_settings.cache_clear()
    settings = Settings(_env_file=None, **REQUIRED_ENV)

    assert settings.explanations_available is False
    assert build_advisor_client(settings) is None


def test_build_advisor_client_returns_a_client_with_a_key():
    settings = Settings(_env_file=None, anthropic_api_key="sk-ant-not-real", **REQUIRED_ENV)

    assert settings.explanations_available is True
    client = build_advisor_client(settings)
    assert client is not None
    # constructing a client makes no network call; nothing here reaches the API
    assert hasattr(client, "complete")


def test_advisor_model_is_configurable():
    settings = Settings(_env_file=None, anthropic_model="claude-sonnet-5", **REQUIRED_ENV)

    assert settings.anthropic_model == "claude-sonnet-5"


def test_cache_key_is_derived_from_the_configured_model(db_session):
    # switching models must not serve the previous model's answers
    client = _FakeAdvisorClient(text=_good_body("1", "2"))
    explain(db_session, _request("1", "2"), client=client, model=MODEL)

    other = _FakeAdvisorClient(text=_good_body("1", "2"))
    outcome = explain(db_session, _request("1", "2"), client=other, model="claude-sonnet-5")

    assert outcome.cached is False
    assert len(other.calls) == 1
    assert cache_key(_request("1", "2"), MODEL) != cache_key(
        _request("1", "2"), "claude-sonnet-5"
    )
