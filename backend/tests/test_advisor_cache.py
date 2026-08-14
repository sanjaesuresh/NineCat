"""Advisor cache: key derivation (plan B5) and the table round trip (A3/B6)."""

import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ninecat.advisor.cache import (
    ADVISOR_CACHE_TTL_SECONDS,
    cache_key,
    read_cached,
    write_cached,
)
from ninecat.advisor.client import AdvisorCompletion
from ninecat.advisor.types import (
    FEATURE_ADDS,
    FEATURE_DRAFT,
    AdvisorRequest,
    AdvisorResult,
    PlayerExplanation,
    ShortlistPlayer,
)
from ninecat.models.advisor import AdvisorCache

MODEL = "claude-opus-5"


def _request(**overrides) -> AdvisorRequest:
    defaults = dict(
        feature=FEATURE_DRAFT,
        situation="pick 12 overall in a 12-team 9-cat league",
        context={"punting": "ft_pct", "roster so far": "Rudy Gobert"},
        shortlist=(
            ShortlistPlayer(
                player_key="1",
                name="Alpha",
                position="PG",
                metrics={"value": 3.4, "rank_score": 3.9},
                tags=("best available",),
            ),
            ShortlistPlayer(player_key="2", name="Beta", position="C", metrics={"value": 3.1}),
        ),
    )
    defaults.update(overrides)
    return AdvisorRequest(**defaults)


def _result() -> AdvisorResult:
    return AdvisorResult(
        model=MODEL,
        summary="Take Alpha.",
        ranked=(
            PlayerExplanation(player_key="1", reasoning="Best all-round value."),
            PlayerExplanation(player_key="2", reasoning="Close second."),
        ),
    )


def _completion() -> AdvisorCompletion:
    return AdvisorCompletion(text="{}", model=MODEL, input_tokens=1200, output_tokens=340)


# --- key derivation ---


def test_identical_inputs_produce_the_same_key():
    assert cache_key(_request(), MODEL) == cache_key(_request(), MODEL)


def test_mapping_insertion_order_does_not_change_the_key():
    a = _request(context={"punting": "ft_pct", "roster so far": "Rudy Gobert"})
    b = _request(context={"roster so far": "Rudy Gobert", "punting": "ft_pct"})
    assert cache_key(a, MODEL) == cache_key(b, MODEL)


def test_a_changed_shortlist_misses():
    changed = _request(
        shortlist=(ShortlistPlayer(player_key="1", name="Alpha", position="PG"),)
    )
    assert cache_key(changed, MODEL) != cache_key(_request(), MODEL)


def test_a_reordered_shortlist_misses():
    # the prompt presents the shortlist in engine order, so a different engine
    # order is a genuinely different question
    original = _request()
    flipped = _request(shortlist=tuple(reversed(original.shortlist)))
    assert cache_key(flipped, MODEL) != cache_key(original, MODEL)


def test_changed_context_misses():
    assert cache_key(_request(context={"punting": "nothing"}), MODEL) != cache_key(
        _request(), MODEL
    )


def test_changed_situation_misses():
    assert cache_key(_request(situation="pick 1 overall"), MODEL) != cache_key(
        _request(), MODEL
    )


def test_a_different_model_misses():
    assert cache_key(_request(), "claude-sonnet-5") != cache_key(_request(), MODEL)


def test_a_different_feature_misses():
    # feature is in the key so entries can never collide across the four
    # features that share this one request shape
    assert cache_key(_request(feature=FEATURE_ADDS), MODEL) != cache_key(_request(), MODEL)


def test_key_is_stable_across_separate_processes():
    """Two fresh interpreters with different hash seeds must agree.

    Asserted across PROCESSES, not two calls in one: PYTHONHASHSEED is fixed for
    a process's lifetime, so any set/dict-iteration-order dependence is
    perfectly stable within a single run and only shows up across runs. Several
    determinism tests elsewhere in this repo make exactly that mistake.
    """
    script = textwrap.dedent(
        """
        from ninecat.advisor.cache import cache_key
        from ninecat.advisor.types import AdvisorRequest, ShortlistPlayer, FEATURE_DRAFT

        request = AdvisorRequest(
            feature=FEATURE_DRAFT,
            situation="pick 12 overall in a 12-team 9-cat league",
            context={"punting": "ft_pct", "roster so far": "Rudy Gobert"},
            shortlist=(
                ShortlistPlayer(
                    player_key="1", name="Alpha", position="PG",
                    metrics={"value": 3.4, "rank_score": 3.9}, tags=("best available",),
                ),
                ShortlistPlayer(
                    player_key="2", name="Beta", position="C", metrics={"value": 3.1}
                ),
            ),
        )
        print(cache_key(request, "claude-opus-5"))
        """
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("0", "1", "12345")
    }

    assert len(digests) == 1
    # and the in-process key agrees with the subprocesses'
    assert digests == {cache_key(_request(), MODEL)}


# --- table round trip ---


def test_write_then_read_returns_the_same_result(db_session):
    key = cache_key(_request(), MODEL)

    write_cached(db_session, key, _request(), _result(), _completion())

    cached = read_cached(db_session, key)
    assert cached == _result()


def test_read_misses_for_an_unknown_key(db_session):
    assert read_cached(db_session, "0" * 64) is None


def test_cached_row_carries_no_user_identifier(db_session):
    """The absence of a user column is what makes an entry shareable (plan B6).

    If a user_id (or anything else user-scoped) were ever added, the same input
    from two users would stop being the same question and the sharing this
    table depends on would silently become a leak.
    """
    key = cache_key(_request(), MODEL)
    write_cached(db_session, key, _request(), _result(), _completion())

    row = db_session.execute(
        select(AdvisorCache).where(AdvisorCache.request_hash == key)
    ).scalar_one()

    assert not hasattr(AdvisorCache, "user_id")
    assert "user" not in {c.name for c in AdvisorCache.__table__.columns}
    assert row.feature == FEATURE_DRAFT
    assert row.model == MODEL
    assert (row.input_tokens, row.output_tokens) == (1200, 340)


def test_write_is_an_upsert_not_a_duplicate_insert(db_session):
    key = cache_key(_request(), MODEL)
    write_cached(db_session, key, _request(), _result(), _completion())

    revised = AdvisorResult(
        model=MODEL,
        summary="Actually take Beta.",
        ranked=(
            PlayerExplanation(player_key="2", reasoning="Reconsidered."),
            PlayerExplanation(player_key="1", reasoning="Still good."),
        ),
    )
    write_cached(db_session, key, _request(), revised, _completion())

    rows = (
        db_session.execute(select(AdvisorCache).where(AdvisorCache.request_hash == key))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert read_cached(db_session, key) == revised


def test_expired_entry_is_treated_as_a_miss(db_session):
    key = cache_key(_request(), MODEL)
    write_cached(db_session, key, _request(), _result(), _completion())

    row = db_session.execute(
        select(AdvisorCache).where(AdvisorCache.request_hash == key)
    ).scalar_one()
    row.created_at = datetime.now(timezone.utc) - timedelta(
        seconds=ADVISOR_CACHE_TTL_SECONDS + 1
    )
    db_session.flush()

    assert read_cached(db_session, key) is None
