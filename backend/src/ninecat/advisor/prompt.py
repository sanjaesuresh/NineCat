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

import re

from ninecat.advisor.types import (
    FEATURE_ADDS,
    FEATURE_DRAFT,
    FEATURE_MATCHUP,
    FEATURE_TRADES,
    AdvisorRequest,
    ShortlistItem,
)

# the rules the model must not break. A1 is enforced in code as well (see
# validation.py) -- stating it here is about getting a usable answer, not about
# trusting the model to obey.
_SYSTEM = """You are an expert fantasy basketball analyst writing for an experienced 9-category \
head-to-head player. You are given a shortlist that an analytics engine has already \
decided is plausible, plus the context behind it.

Your job:
- Rank the shortlist, best option first.
- Write one short explanation per entry: why it sits where it does, in terms of \
this specific context.

Hard rules:
- Use only the entries in the shortlist. Never introduce an option that is not on it, \
and never drop one. Ranking within the shortlist is the only reordering allowed.
- Never argue against a punt the user has chosen. Take it as settled and reason inside it.
- The numbers you are given are the only numbers. Do not invent stats, injuries, \
news, or transactions.
- If two options are genuinely close, say so plainly rather than manufacturing a \
difference.

Style: direct and concrete. Two sentences per entry at most. No preamble, no \
restating the question, no hedging filler. Write for someone who already knows the \
category abbreviations.

Vocabulary: the nine categories are FG%, FT%, 3PM, PTS, REB, AST, ST, BLK, TO -- \
always write them exactly that way. Never use internal identifiers in your prose: \
no snake_case tokens, and never an item_key (item_key belongs only in the structured \
field you return). Refer to every entry by its name or label."""

# one line of feature-specific framing plus what that feature's shortlist
# entries actually ARE, so the same generic shape produces advice that sounds
# like it is about the decision in front of the user
_FEATURE_FRAMING = {
    FEATURE_DRAFT: (
        "This is a draft pick decision. Each entry is a player you could take with this "
        "pick. Weigh long-run roster fit and positional scarcity, not one week of production."
    ),
    FEATURE_MATCHUP: (
        "This is a weekly streaming decision inside a head-to-head matchup. Each entry is "
        "one add on one day. Weigh what actually moves categories in this specific week, "
        "and be honest when an add is marginal."
    ),
    FEATURE_ADDS: (
        "This is a waiver/free-agent decision. Each entry is a player who could be added. "
        "Weigh what the roster is short of and how long the player is likely to hold value."
    ),
    FEATURE_TRADES: (
        "This is a trade decision. Each entry is one proposed trade -- what you give and "
        "what you get. Weigh what each side gives up in category terms, not just aggregate "
        "value, and say plainly when a proposal is not worth making."
    ),
}


# canonical engine key -> the display name an experienced 9-cat player writes.
# translation happens HERE, at the prompt boundary, because the model parrots
# whatever vocabulary it is fed -- raw keys in the input came straight back out
# in prose and onto the page (wp7 live finding). word-boundary regex so player
# names and ordinary words are never touched.
_CATEGORY_DISPLAY = {
    "fg_pct": "FG%",
    "ft_pct": "FT%",
    "tpm": "3PM",
    "pts": "PTS",
    "reb": "REB",
    "ast": "AST",
    "stl": "ST",
    "blk": "BLK",
    "tov": "TO",
}
_CATEGORY_KEY_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(sorted(_CATEGORY_DISPLAY, key=len, reverse=True)) + r")(?![A-Za-z0-9_])"
)


def _display_categories(text: str) -> str:
    return _CATEGORY_KEY_RE.sub(lambda m: _CATEGORY_DISPLAY[m.group(1)], text)


def _display_metric_key(key: str) -> str:
    # category keys get their display names; anything else drops the
    # snake_case ("rank_score" read as an identifier and came back verbatim
    # in live prose -- "rank score" reads as english instead)
    return _CATEGORY_DISPLAY.get(key, key.replace("_", " "))


def build_prompt(request: AdvisorRequest) -> tuple[str, str]:
    """Return (system, user). Pure: no network, no clock, no database."""
    lines: list[str] = [_FEATURE_FRAMING[request.feature], ""]
    lines.append(f"Situation: {_display_categories(request.situation)}")

    if request.context:
        lines.append("")
        lines.append("Context:")
        for label in sorted(request.context):
            lines.append(
                f"- {_display_categories(label)}: {_display_categories(str(request.context[label]))}"
            )

    lines.append("")
    lines.append("Shortlist (engine order):")
    for item in request.shortlist:
        lines.append(f"- {_render_item(item)}")

    lines.append("")
    lines.append(
        "Return every shortlist entry exactly once, best first, each with its "
        "item_key copied verbatim, plus a one-line summary of the call."
    )
    return _SYSTEM, "\n".join(lines)


def _render_item(item: ShortlistItem) -> str:
    parts = [f"[{item.item_key}] {item.label}"]
    if item.detail:
        parts.append(_display_categories(item.detail))
    if item.metrics:
        # sorted so the same metrics dict always renders the same way
        metrics = ", ".join(
            f"{_display_metric_key(k)} {item.metrics[k]}" for k in sorted(item.metrics)
        )
        parts.append(metrics)
    if item.tags:
        # tags arrive as an ordered tuple from the engine and stay in that
        # order -- it is the engine's own ranking of what matters most
        parts.append("; ".join(_display_categories(t) for t in item.tags))
    return " | ".join(parts)
