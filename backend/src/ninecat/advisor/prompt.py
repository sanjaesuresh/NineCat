"""Prompt building: a pure function from AdvisorRequest to the two strings the
API call needs (plan B2).

Kept separate from the client so that "exactly what do we send" is a cheap unit
test rather than an integration exercise -- which is what makes the mandatory
no-secrets test (plan A4) possible at all.

Byte-stability matters here: the rendered prompt is not itself the cache key,
but it is built from the same inputs, so anything that varied per process
(dict/set iteration order) would make the two disagree. Every mapping is walked
in sorted key order for that reason.
"""

from __future__ import annotations

from ninecat.advisor.types import (
    FEATURE_ADDS,
    FEATURE_DRAFT,
    FEATURE_MATCHUP,
    FEATURE_TRADES,
    AdvisorRequest,
)

# the rules the model must not break. A1 is enforced in code as well (see
# validation.py) -- stating it here is about getting a usable answer, not about
# trusting the model to obey.
_SYSTEM = """You are an expert fantasy basketball analyst writing for an experienced 9-category \
head-to-head player. You are given a shortlist that an analytics engine has already \
decided is plausible, plus the context behind it.

Your job:
- Rank the shortlist, best option first.
- Write one short explanation per player: why it sits where it does, in terms of \
this specific context.

Hard rules:
- Use only the players in the shortlist. Never introduce a player who is not on it, \
and never drop one. Ranking within the shortlist is the only reordering allowed.
- Never argue against a punt the user has chosen. Take it as settled and reason inside it.
- The numbers you are given are the only numbers. Do not invent stats, injuries, \
news, or transactions.
- If two options are genuinely close, say so plainly rather than manufacturing a \
difference.

Style: direct and concrete. Two sentences per player at most. No preamble, no \
restating the question, no hedging filler. Write for someone who already knows the \
category abbreviations."""

# one line of feature-specific framing, so the same shape produces advice that
# sounds like it is about the decision actually in front of the user
_FEATURE_FRAMING = {
    FEATURE_DRAFT: "This is a draft pick decision. Weigh long-run roster fit and positional scarcity, not one week of production.",
    FEATURE_MATCHUP: "This is a weekly matchup decision. Weigh what moves categories in this specific week.",
    FEATURE_ADDS: "This is a waiver/free-agent decision. Weigh what the roster is short of and how long the player is likely to hold value.",
    FEATURE_TRADES: "This is a trade decision. Weigh what each side gives up in category terms, not just aggregate value.",
}


def build_prompt(request: AdvisorRequest) -> tuple[str, str]:
    """Return (system, user). Pure: no network, no clock, no database."""
    lines: list[str] = [_FEATURE_FRAMING[request.feature], ""]
    lines.append(f"Situation: {request.situation}")

    if request.context:
        lines.append("")
        lines.append("Context:")
        for label in sorted(request.context):
            lines.append(f"- {label}: {request.context[label]}")

    lines.append("")
    lines.append("Shortlist (engine order):")
    for player in request.shortlist:
        lines.append(f"- {_render_player(player)}")

    lines.append("")
    lines.append(
        "Return every shortlist player exactly once, best first, each with its "
        "player_key copied verbatim, plus a one-line summary of the call."
    )
    return _SYSTEM, "\n".join(lines)


def _render_player(player) -> str:
    position = player.position or "unknown position"
    parts = [f"[{player.player_key}] {player.name} ({position})"]
    if player.metrics:
        # sorted so the same metrics dict always renders the same way
        metrics = ", ".join(f"{k} {player.metrics[k]}" for k in sorted(player.metrics))
        parts.append(metrics)
    if player.tags:
        # tags arrive as an ordered tuple from the engine and stay in that
        # order -- it is the engine's own ranking of what matters most
        parts.append("; ".join(player.tags))
    return " | ".join(parts)
