"""Loader for research evidence JSON files into a typed, name-indexed store.

Later projection stages consult this store (consensus rankings, transactions,
injuries, role notes, rookie notes, forum sentiment) to nudge the statistical
baseline. Every evidence item is validated against nineproj.research.schema
at load time so malformed research fails loudly instead of silently dropping
evidence mid-pipeline.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from nineproj.config import Settings
from nineproj.research.schema import (
    ConsensusList,
    InjuryNote,
    RoleNote,
    RookieNote,
    SentimentNote,
    TransactionEvent,
)

# mirrors backend/src/ninecat/warehouse/id_mapping.py normalize_name --
# reimplemented locally (not imported) since that module pulls in
# SQLAlchemy/DB models this DB-agnostic pipeline must not depend on
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_HYPHEN_TO_SPACE = re.compile(r"-")
_NON_ALNUM_SPACE = re.compile(r"[^a-z0-9\s]")


def normalize_name(name: str) -> str:
    """Lowercase, diacritic-strip, punctuation-fold, and suffix-strip a player name.

    Makes "Test Star A" == "test star a." (stray trailing period) comparable
    without a hardcoded per-player alias table.
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


_KIND_TO_MODEL = {
    "transaction": TransactionEvent,
    "injury": InjuryNote,
    "role": RoleNote,
    "rookie": RookieNote,
    "sentiment": SentimentNote,
}


def _index_by_name(items: list) -> dict[str, list]:
    """Group evidence items by normalized player name for O(1) lookup."""
    index: dict[str, list] = defaultdict(list)
    for item in items:
        index[normalize_name(item.player)].append(item)
    return index


@dataclass
class EvidenceStore:
    """Typed research evidence, indexed by normalized player name."""

    transactions: list[TransactionEvent] = field(default_factory=list)
    injuries: list[InjuryNote] = field(default_factory=list)
    roles: list[RoleNote] = field(default_factory=list)
    rookies: list[RookieNote] = field(default_factory=list)
    sentiment: list[SentimentNote] = field(default_factory=list)
    consensus_lists: list[ConsensusList] = field(default_factory=list)

    def __post_init__(self) -> None:
        # build the name indices once at construction rather than scanning on every lookup
        self._transactions_by_name = _index_by_name(self.transactions)
        self._injuries_by_name = _index_by_name(self.injuries)
        self._roles_by_name = _index_by_name(self.roles)
        self._rookies_by_name = _index_by_name(self.rookies)
        self._sentiment_by_name = _index_by_name(self.sentiment)

    def transactions_for(self, name: str) -> list[TransactionEvent]:
        return self._transactions_by_name.get(normalize_name(name), [])

    def injuries_for(self, name: str) -> list[InjuryNote]:
        return self._injuries_by_name.get(normalize_name(name), [])

    def roles_for(self, name: str) -> list[RoleNote]:
        return self._roles_by_name.get(normalize_name(name), [])

    def rookie_for(self, name: str) -> RookieNote | None:
        # a player has at most one rookie note in practice; last-loaded wins
        # on the rare chance a fixture set somehow has more than one
        matches = self._rookies_by_name.get(normalize_name(name), [])
        return matches[-1] if matches else None

    def sentiment_for(self, name: str) -> list[SentimentNote]:
        return self._sentiment_by_name.get(normalize_name(name), [])


def load_store(dir_path: str | Path, settings: Settings) -> EvidenceStore:
    """Walk dir_path recursively, validating every *.json file into typed evidence.

    Each file is either a single consensus ranking ({"consensus_list": {...}})
    or a batch of same-kind evidence notes ({"kind": ..., "items": [...]}).
    Raises ValueError naming the offending file on any validation failure, so
    a malformed research fixture fails loudly rather than dropping evidence
    silently.
    """
    root = Path(dir_path)
    buckets: dict[str, list] = {kind: [] for kind in _KIND_TO_MODEL}
    consensus_lists: list[ConsensusList] = []

    for json_path in sorted(root.rglob("*.json")):
        try:
            # json.loads lives inside the try too -- a syntactically broken
            # file must still name the offending path, not raise a bare
            # JSONDecodeError with no file context
            raw = json.loads(json_path.read_text())
            if "consensus_list" in raw:
                consensus_lists.append(ConsensusList(**raw["consensus_list"]))
                continue

            kind = raw.get("kind")
            model = _KIND_TO_MODEL.get(kind)
            if model is None:
                raise ValueError(f"unknown or missing 'kind': {kind!r}")
            items = [model(**item) for item in raw["items"]]
        except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid research fixture {json_path}: {exc}") from exc

        # attach each item's quality-tier weight now, at load time, so
        # downstream consumers never need settings in hand to read .weight
        for evidence_item in items:
            evidence_item.weight = getattr(
                settings.consensus.quality_tier_weights, evidence_item.source.quality_tier
            )
        buckets[kind].extend(items)

    return EvidenceStore(
        transactions=buckets["transaction"],
        injuries=buckets["injury"],
        roles=buckets["role"],
        rookies=buckets["rookie"],
        sentiment=buckets["sentiment"],
        consensus_lists=consensus_lists,
    )
