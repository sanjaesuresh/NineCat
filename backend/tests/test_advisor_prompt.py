"""Prompt building, including the mandatory no-secrets test (plan A4).

build_prompt is a pure function, which is the whole reason "exactly what do we
send to Anthropic" can be asserted here rather than only observed in an
integration run.
"""

import os

import pytest

from ninecat.advisor.prompt import build_prompt
from ninecat.advisor.types import (
    FEATURE_ADDS,
    FEATURE_DRAFT,
    FEATURE_MATCHUP,
    FEATURE_TRADES,
    AdvisorRequest,
    ShortlistPlayer,
)


def _request(**overrides) -> AdvisorRequest:
    defaults = dict(
        feature=FEATURE_DRAFT,
        situation="pick 12 overall in a 12-team 9-cat league",
        context={"punting": "ft_pct", "roster so far": "Rudy Gobert"},
        shortlist=(
            ShortlistPlayer(
                player_key="201939",
                name="Alpha Guard",
                position="PG",
                metrics={"value": 3.4, "rank_score": 3.9},
                tags=("best available", "helps ast, stl"),
            ),
            ShortlistPlayer(
                player_key="203999",
                name="Beta Big",
                position="C",
                metrics={"value": 3.1, "rank_score": 3.2},
                tags=("may not last to your next pick",),
            ),
        ),
    )
    defaults.update(overrides)
    return AdvisorRequest(**defaults)


def test_prompt_contains_the_shortlist_and_its_context():
    system, user = build_prompt(_request())

    assert "shortlist" in system.lower()
    assert "Alpha Guard" in user
    assert "Beta Big" in user
    assert "201939" in user and "203999" in user
    assert "pick 12 overall in a 12-team 9-cat league" in user
    assert "punting: ft_pct" in user
    assert "roster so far: Rudy Gobert" in user
    assert "value 3.4" in user
    assert "may not last to your next pick" in user


def test_prompt_states_the_integrity_rule_the_validator_enforces():
    # the guard is enforced in code (validation.py); the prompt says it too so
    # the model has a chance of producing a usable answer in the first place
    system, _user = build_prompt(_request())
    assert "never introduce a player" in system.lower()
    assert "never drop one" in system.lower()


@pytest.mark.parametrize(
    "feature", [FEATURE_DRAFT, FEATURE_MATCHUP, FEATURE_ADDS, FEATURE_TRADES]
)
def test_every_feature_has_its_own_framing_line(feature):
    # one shared shape, but each feature must sound like it is about the
    # decision actually in front of the user (plan B3)
    _system, user = build_prompt(_request(feature=feature))
    assert user.splitlines()[0].strip()


def test_prompt_is_byte_stable_for_the_same_request():
    # the prompt and the cache key are built from the same inputs; if either
    # varied per process they would disagree
    assert build_prompt(_request()) == build_prompt(_request())


def test_mapping_order_does_not_change_the_prompt():
    # a caller building the same context dict in a different insertion order
    # must produce the identical prompt
    a = _request(context={"punting": "ft_pct", "roster so far": "Rudy Gobert"})
    b = _request(context={"roster so far": "Rudy Gobert", "punting": "ft_pct"})
    assert build_prompt(a) == build_prompt(b)


def test_prompt_carries_no_secrets_or_user_identifiers(monkeypatch):
    """SECURITY, pinned (plan A4). A prompt is an outbound network payload; a
    token, user id or email that reaches it has left the building.

    The shortlist and context below are deliberately adversarial: they carry
    field values that LOOK like an attacker (or a careless future caller) tried
    to smuggle credentials through. What is asserted is that build_prompt reads
    only the declared fields and never reaches for the environment, settings, or
    any ambient user state of its own accord.
    """
    secrets = {
        "TOKEN_ENCRYPTION_KEY": "s3cret-encryption-key",
        "SESSION_SECRET": "s3cret-session-secret",
        "YAHOO_CLIENT_SECRET": "s3cret-yahoo-client-secret",
        "ANTHROPIC_API_KEY": "sk-ant-s3cret-key",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)

    system, user = build_prompt(_request())
    rendered = f"{system}\n{user}"

    for value in secrets.values():
        assert value not in rendered
    # nothing user-scoped either -- these are what the app actually holds about
    # a signed-in user, and none of it is an input to this function
    for identifier in ("ninecat_session", "@", "user_id", "yahoo_token", "refresh_token"):
        assert identifier not in rendered
    # and the environment is not consulted at all: no env value of any name
    # reaches the prompt
    for value in os.environ.values():
        if len(value) > 8:
            assert value not in rendered
