"""NBA-position to Yahoo-slot-class eligibility mapping.

This is a coarse fallback: nba_api positions ("Guard", "PG", "F-C", ...) are far
less precise than Yahoo's own eligible_positions, which reflects a player's actual
roster-slot eligibility for a given league. Once live Yahoo player data is wired
in, eligible_positions should override whatever this module infers.
"""

from __future__ import annotations

import re

# canonical order for the eight Yahoo roster slot classes this module ever returns
SLOT_CLASSES = ("PG", "SG", "G", "SF", "PF", "F", "C", "UTIL")

# a token maps to the slot classes it's eligible for, minus UTIL (added uniformly
# below). Specific short forms ("PG") are narrower than their generic/long
# counterparts ("Guard", "G") since a specifically-labeled point guard isn't
# automatically shooting-guard eligible, but a generic "Guard"/"G" is both.
_TOKEN_CLASSES: dict[str, frozenset[str]] = {
    "guard": frozenset({"PG", "SG", "G"}),
    "g": frozenset({"PG", "SG", "G"}),
    "forward": frozenset({"SF", "PF", "F"}),
    "f": frozenset({"SF", "PF", "F"}),
    "center": frozenset({"C"}),
    "c": frozenset({"C"}),
    "pg": frozenset({"PG", "G"}),
    "sg": frozenset({"SG", "G"}),
    "sf": frozenset({"SF", "F"}),
    "pf": frozenset({"PF", "F"}),
}

# nba_api multi-position strings are hyphen- or slash-separated ("Guard-Forward",
# "F-C", "PG/SG"); Yahoo's display_position is comma-delimited ("PG,SG") --
# accept all three separators so either source parses correctly
_TOKEN_SPLIT_RE = re.compile(r"[-/,]")


def slot_classes(position: str | None) -> frozenset[str]:
    """Map a stored NbaPlayer.position string to the Yahoo slot classes it fills.

    None, blank, or wholly unrecognizable input falls back to UTIL-only (a
    player can always fill a UTIL slot) rather than raising, since sync data is
    sometimes missing or oddly formatted.
    """
    if not position or not position.strip():
        return frozenset({"UTIL"})

    classes: set[str] = set()
    for token in _TOKEN_SPLIT_RE.split(position):
        mapped = _TOKEN_CLASSES.get(token.strip().lower())
        if mapped:
            classes |= mapped

    if not classes:
        return frozenset({"UTIL"})
    classes.add("UTIL")
    return frozenset(classes)
