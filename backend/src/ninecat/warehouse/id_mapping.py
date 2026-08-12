"""Match Yahoo fantasy players to warehouse NbaPlayer rows, tracking the method used.

Yahoo and NBA.com don't share a stable player id, so this bridges them by name:
try an exact string match first, fall back to a normalized match (diacritics,
punctuation, and generational suffixes stripped) if that fails or is
ambiguous, and otherwise leave the player unmatched for a human to resolve
later. Once a yahoo_player_key has a PlayerIdMap row -- matched, unmatched, or
a human's manual fix -- it is never touched again by this function.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ninecat.models.warehouse import NbaPlayer, PlayerIdMap
from ninecat.yahoo.parsers import RosterEntry

# trailing generational-suffix tokens stripped during normalization, so
# "Jaren Jackson Jr." (yahoo) and "Jaren Jackson Jr" (nba.com) normalize equal
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
# only a hyphen folds to a space ("Metu-Wiggins" is genuinely two words on
# the other side); periods/apostrophes are deleted outright below instead of
# spaced, so "P.J." and "De'Aaron" collapse to "pj"/"deaaron", not "p j"/"de aaron"
_HYPHEN_TO_SPACE = re.compile(r"-")
_NON_ALNUM_SPACE = re.compile(r"[^a-z0-9\s]")


def normalize_name(name: str) -> str:
    """Lowercase, diacritic-strip, punctuation-fold, and suffix-strip a player name.

    Makes "Luka Dončić" == "Luka Doncic", "Jaren Jackson Jr." == "Jaren
    Jackson Jr", "P.J. Washington" == "PJ Washington", and "De'Aaron Fox" ==
    "DeAaron Fox" comparable without a hardcoded per-player alias table.
    """
    # NFD decomposes an accented letter into base + combining mark; dropping
    # combining marks is what turns "č"/"ć" into plain "c"
    decomposed = unicodedata.normalize("NFD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = stripped.lower()
    hyphen_spaced = _HYPHEN_TO_SPACE.sub(" ", lowered)
    # deletes (not spaces) any remaining non-alnum char, which includes
    # periods and apostrophes -- they fuse their neighbors rather than split them
    cleaned = _NON_ALNUM_SPACE.sub("", hyphen_spaced)
    tokens = cleaned.split()
    if tokens and tokens[-1] in _SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


@dataclass(frozen=True)
class MappingResult:
    """Outcome of one map_yahoo_players call."""

    exact_matches: int = 0
    normalized_matches: int = 0
    unmatched: list[str] = field(default_factory=list)
    # yahoo_player_keys that already had a PlayerIdMap row and were skipped
    already_mapped: int = 0


def map_yahoo_players(session: Session, yahoo_players: Sequence[RosterEntry]) -> MappingResult:
    """Link each Yahoo roster entry to an NbaPlayer by name, or record it unmatched.

    Never re-matches a yahoo_player_key that already has a PlayerIdMap row --
    of any method, including "manual" -- so a human's manual fix (or a prior
    matched/unmatched decision) survives every later re-run of a sync.
    """
    if not yahoo_players:
        return MappingResult()

    # dedupe the input by yahoo_player_key first (last occurrence wins): a
    # caller could pass the same roster entry twice in one batch, and a
    # single multi-row INSERT can't target the same conflict key more than
    # once (postgres rejects it outright, even under DO NOTHING)
    deduped_by_key: dict[str, RosterEntry] = {}
    for entry in yahoo_players:
        deduped_by_key[entry.player_key] = entry
    deduped_players = list(deduped_by_key.values())

    existing_keys = set(
        session.execute(
            select(PlayerIdMap.yahoo_player_key).where(
                PlayerIdMap.yahoo_player_key.in_(deduped_by_key.keys())
            )
        )
        .scalars()
        .all()
    )

    to_process = [entry for entry in deduped_players if entry.player_key not in existing_keys]
    already_mapped = len(deduped_players) - len(to_process)
    if not to_process:
        return MappingResult(already_mapped=already_mapped)

    # load every NbaPlayer once and index by exact + normalized name, rather
    # than a query per yahoo entry -- cheap at league-roster scale (hundreds
    # of players), and lets ambiguity be detected as "2+ entries in a bucket"
    all_players = session.execute(select(NbaPlayer)).scalars().all()
    by_full_name: dict[str, list[NbaPlayer]] = defaultdict(list)
    by_normalized: dict[str, list[NbaPlayer]] = defaultdict(list)
    for player in all_players:
        by_full_name[player.full_name].append(player)
        by_normalized[normalize_name(player.full_name)].append(player)

    exact_matches = 0
    normalized_matches = 0
    unmatched_names: list[str] = []
    rows_to_add: list[dict] = []

    for entry in to_process:
        exact_candidates = by_full_name.get(entry.name, [])
        if len(exact_candidates) == 1:
            rows_to_add.append(
                {
                    "nba_player_id": exact_candidates[0].id,
                    "yahoo_player_key": entry.player_key,
                    "yahoo_name": entry.name,
                    "match_method": "exact",
                }
            )
            exact_matches += 1
            continue

        # ambiguous at the exact stage (2+ NbaPlayers share this exact name)
        # stops here -- never falls through to a normalized guess on a name
        # that's already ambiguous; only an exact-stage MISS tries normalized
        if len(exact_candidates) == 0:
            normalized_candidates = by_normalized.get(normalize_name(entry.name), [])
            if len(normalized_candidates) == 1:
                rows_to_add.append(
                    {
                        "nba_player_id": normalized_candidates[0].id,
                        "yahoo_player_key": entry.player_key,
                        "yahoo_name": entry.name,
                        "match_method": "normalized",
                    }
                )
                normalized_matches += 1
                continue

        rows_to_add.append(
            {
                "nba_player_id": None,
                "yahoo_player_key": entry.player_key,
                "yahoo_name": entry.name,
                "match_method": "unmatched",
            }
        )
        unmatched_names.append(entry.name)

    if rows_to_add:
        insert_stmt = pg_insert(PlayerIdMap).values(rows_to_add)
        # DO NOTHING (not DO UPDATE): a concurrent run racing on the same
        # yahoo_player_key must never clobber a manual fix or an earlier
        # decision -- silently skipping on conflict enforces the "never
        # re-match automatically" rule at the statement level too, not just
        # via the existing_keys pre-filter above
        stmt = insert_stmt.on_conflict_do_nothing(index_elements=[PlayerIdMap.yahoo_player_key])
        session.execute(stmt)

    return MappingResult(
        exact_matches=exact_matches,
        normalized_matches=normalized_matches,
        unmatched=unmatched_names,
        already_mapped=already_mapped,
    )
