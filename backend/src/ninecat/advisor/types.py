"""The one request/result shape every feature shares (plan B3).

Draft picks, streaming adds, waiver candidates and trade proposals differ in
what fills the shortlist, but they all ask the same question: rank these, and
explain each. One shape means one prompt builder, one validator, one cache and
one frontend component instead of four of each. `feature` travels as a field so
the prompt can differ where it must and cache keys never collide across
features.

The shortlist is a list of ITEMS, not players. Three of the four features do
rank players, but a trade proposal is a give/get pair with no single player to
name -- so the shape is generic and each feature says what its items are. This
is the adjustment the build plan stopped after Draft to make.

Nothing here touches the network, the clock, or the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# bumped whenever the prompt text or the response contract changes in a way
# that makes previously cached answers wrong. It is part of the cache key, so a
# bump invalidates every stored entry without needing a data migration.
# v2: shortlist entries became generic items (item_key/label) rather than
# players, so every v1 prompt and every v1 cached answer is a different shape.
PROMPT_VERSION = 2

# feature identifiers -- structured tokens, never prose. They key the cache and
# select prompt wording, so they are a contract, not a display string.
FEATURE_DRAFT = "draft"
FEATURE_MATCHUP = "matchup"
FEATURE_ADDS = "adds"
FEATURE_TRADES = "trades"
FEATURES = (FEATURE_DRAFT, FEATURE_MATCHUP, FEATURE_ADDS, FEATURE_TRADES)

# why explanations are missing. Structured tokens the frontend maps to copy --
# the backend never emits English prose for these (same discipline as
# api/routes.py's OPPONENT_REASON_* tokens).
REASON_NOT_CONFIGURED = "not_configured"
REASON_TIMEOUT = "timeout"
REASON_RATE_LIMITED = "rate_limited"
REASON_AUTH = "auth_error"
REASON_CONNECTION = "connection_error"
REASON_OVERLOADED = "overloaded"
REASON_API_ERROR = "api_error"
REASON_REFUSED = "refused"
REASON_MALFORMED = "malformed_response"
REASON_SHORTLIST_MISMATCH = "shortlist_mismatch"
REASON_EMPTY_SHORTLIST = "empty_shortlist"


@dataclass(frozen=True)
class ShortlistItem:
    """One candidate the engine already decided is plausible.

    `metrics` and `tags` are whatever that feature's engine computed and would
    show the user anyway -- they are display data, so putting them in a prompt
    leaks nothing (plan A4). There is deliberately no field for anything
    user-scoped; see the no-secrets test.
    """

    # opaque and stable within one request; the model echoes it back and the
    # integrity guard matches on it. Whatever the feature uses to identify a
    # row it already renders -- a player key, or a synthetic key for a proposal.
    item_key: str
    # what to call this item, e.g. a player's name or "give A, get B"
    label: str
    # optional second line, e.g. a position or a proposal's category effects
    detail: str | None = None
    # label -> already-rounded number, e.g. {"value": 3.41, "pts": 1.08}
    metrics: dict[str, float] = field(default_factory=dict)
    # engine-emitted structured facts, already rendered for display
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdvisorRequest:
    """A shortlist plus the context needed to reason about it."""

    feature: str
    # one line framing the decision, e.g. "the 12th overall pick"
    situation: str
    # label -> value, rendered into the prompt verbatim. Same rule as
    # ShortlistItem: display data only, never identifiers or credentials.
    context: dict[str, str] = field(default_factory=dict)
    shortlist: tuple[ShortlistItem, ...] = ()

    def __post_init__(self) -> None:
        if self.feature not in FEATURES:
            raise ValueError(f"unknown advisor feature: {self.feature!r}")

    def item_keys(self) -> tuple[str, ...]:
        return tuple(item.item_key for item in self.shortlist)


@dataclass(frozen=True)
class ItemExplanation:
    item_key: str
    reasoning: str


@dataclass(frozen=True)
class AdvisorResult:
    """A validated response: the shortlist reordered, plus per-item prose.

    `model` is carried so the UI can attribute the text (A6) -- the user must
    always be able to tell which parts are arithmetic and which are judgement.
    """

    model: str
    summary: str
    # shortlist order as the model ranked it; membership is guaranteed
    # identical to the request's shortlist (the A1 integrity guard)
    ranked: tuple[ItemExplanation, ...]


@dataclass(frozen=True)
class AdvisorOutcome:
    """What the service hands back. Exactly one of result/reason is set --
    callers switch on `result is None` rather than on the reason token."""

    result: AdvisorResult | None
    reason: str | None
    # true when served from the advisor cache rather than a fresh API call;
    # observability only, never shown to the user
    cached: bool = False


# constrains the API response at the request level (structured outputs). This
# does NOT replace validation.py's checks: a schema can say "a list of
# {item_key, reasoning}", but it cannot say WHICH item_keys are legal, and
# that is the guarantee A1 actually depends on.
RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["item_key", "reasoning"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "ranked"],
    "additionalProperties": False,
}
