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
    ShortlistItem,
)


def _request(**overrides) -> AdvisorRequest:
    defaults = dict(
        feature=FEATURE_DRAFT,
        situation="pick 12 overall in a 12-team 9-cat league",
        context={"punting": "ft_pct", "roster so far": "Rudy Gobert"},
        shortlist=(
            ShortlistItem(
                item_key="201939",
                label="Alpha Guard",
                detail="PG",
                metrics={"value": 3.4, "rank_score": 3.9},
                tags=("best available", "helps ast, stl"),
            ),
            ShortlistItem(
                item_key="203999",
                label="Beta Big",
                detail="C",
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
    assert "punting: FT%" in user  # raw keys are translated at the prompt boundary (wp7)
    assert "roster so far: Rudy Gobert" in user
    assert "value 3.4" in user
    assert "may not last to your next pick" in user


def test_prompt_states_the_integrity_rule_the_validator_enforces():
    # the guard is enforced in code (validation.py); the prompt says it too so
    # the model has a chance of producing a usable answer in the first place
    system, _user = build_prompt(_request())
    assert "never introduce an option that is not on it" in system.lower()
    assert "never drop one" in system.lower()


@pytest.mark.parametrize(
    "feature", [FEATURE_DRAFT, FEATURE_MATCHUP, FEATURE_ADDS, FEATURE_TRADES]
)
def test_every_feature_says_what_its_shortlist_entries_are(feature):
    """One generic shape, four decisions. The framing line is what stops a
    trade proposal being described to the model as if it were a draft pick --
    the shortlist is items, and only this line says what kind."""
    _system, user = build_prompt(_request(feature=feature))
    framing = user.splitlines()[0]

    assert framing.strip()
    assert "Each entry is" in framing


def test_feature_framings_are_all_distinct():
    framings = {
        build_prompt(_request(feature=f))[1].splitlines()[0]
        for f in (FEATURE_DRAFT, FEATURE_MATCHUP, FEATURE_ADDS, FEATURE_TRADES)
    }
    assert len(framings) == 4


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


def test_prompt_renders_category_display_names_never_raw_keys():
    # wp7 live finding: raw engine keys fed into the prompt came straight back
    # out in the model's prose ("fills fg_pct, reb and blk") and onto the page
    request = AdvisorRequest(
        feature=FEATURE_TRADES,
        situation="Testing categories.",
        context={"deficits": "fg_pct, reb, blk", "surplus": "tpm, ast"},
        shortlist=(
            ShortlistItem(
                item_key="proposal-0",
                label="give A / get B",
                detail="fills fg_pct and reb for tpm",
                metrics={"fg_pct": 0.5, "tov": 2.1},
                tags=("helps fg_pct, tpm", "costs tov"),
            ),
        ),
    )
    _system, user = build_prompt(request)
    for raw in ("fg_pct", "tpm", "tov"):
        assert raw not in user, f"raw key {raw!r} reached the prompt"
    assert "FG%" in user
    assert "3PM" in user
    assert "TO" in user


def test_prompt_humanizes_non_category_metric_keys():
    # "rank_score 6.6" in the prompt came back as "Top rank_score on the
    # board" in live prose -- snake_case metric names read as identifiers to
    # the model, so they are spaced at the boundary too
    request = AdvisorRequest(
        feature=FEATURE_DRAFT,
        situation="s",
        context={},
        shortlist=(
            ShortlistItem(
                item_key="1",
                label="Player",
                detail=None,
                metrics={"rank_score": 6.6, "games_remaining": 3},
                tags=(),
            ),
        ),
    )
    _system, user = build_prompt(request)
    assert "rank_score" not in user
    assert "rank score 6.6" in user
    assert "games remaining 3" in user


def test_system_prompt_bans_identifier_prose():
    request = AdvisorRequest(
        feature=FEATURE_DRAFT,
        situation="s",
        context={},
        shortlist=(ShortlistItem(item_key="1", label="Player", detail=None, metrics={}, tags=()),),
    )
    system, _user = build_prompt(request)
    assert "item_key" in system  # the rule must name what is banned from prose
    assert "FG%" in system  # the category vocabulary is stated explicitly
