"""Claude advisor: turns an engine shortlist into a ranked, explained one.

The engine decides what is plausible; this layer explains why and breaks ties on
judgement the math does not capture. Without an API key the product keeps
working, deterministically, and says so. See docs/claude-advisor-plan.md.
"""

from ninecat.advisor.client import (
    AdvisorClient,
    AdvisorCompletion,
    AdvisorUnavailable,
    AnthropicAdvisorClient,
)
from ninecat.advisor.prompt import build_prompt
from ninecat.advisor.service import build_advisor_client, explain
from ninecat.advisor.types import (
    FEATURE_ADDS,
    FEATURE_DRAFT,
    FEATURE_MATCHUP,
    FEATURE_TRADES,
    PROMPT_VERSION,
    REASON_NOT_CONFIGURED,
    AdvisorOutcome,
    AdvisorRequest,
    AdvisorResult,
    PlayerExplanation,
    ShortlistPlayer,
)
from ninecat.advisor.validation import AdvisorRejected, validate_response

__all__ = [
    "AdvisorClient",
    "AdvisorCompletion",
    "AdvisorOutcome",
    "AdvisorRejected",
    "AdvisorRequest",
    "AdvisorResult",
    "AdvisorUnavailable",
    "AnthropicAdvisorClient",
    "FEATURE_ADDS",
    "FEATURE_DRAFT",
    "FEATURE_MATCHUP",
    "FEATURE_TRADES",
    "PROMPT_VERSION",
    "REASON_NOT_CONFIGURED",
    "PlayerExplanation",
    "ShortlistPlayer",
    "build_advisor_client",
    "build_prompt",
    "explain",
    "validate_response",
]
