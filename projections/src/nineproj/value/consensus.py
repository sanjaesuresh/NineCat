"""Consensus ranking model and model-vs-consensus disagreement flags (Task 12).

Blends multiple ConsensusList rankings (expert boards, ADP, community, etc.)
from the research evidence store into one weighted-average rank per player,
then compares that consensus against our own model rank to flag notable
disagreements the pipeline should surface for review.
"""

from __future__ import annotations

from dataclasses import dataclass

from nineproj.config import Settings
from nineproj.research.schema import ConsensusList
from nineproj.research.store import normalize_name


@dataclass
class ConsensusResult:
    consensus_rank: float | None
    sources_used: int
    rank_variance: float | None
    per_source: dict[str, dict[str, int | bool]]


@dataclass
class Disagreement:
    rank_difference: float | None
    flag: str


def _source_weight(source, settings: Settings) -> float:
    # weight = how much this source's type matters x how much we trust its tier
    type_weight = getattr(settings.consensus.source_type_weights, source.type)
    tier_weight = getattr(settings.consensus.quality_tier_weights, source.quality_tier)
    return type_weight * tier_weight


# a matched first name must be at least this many chars -- floor of 2 (not 3)
# specifically so "Lu"/"Luguentz" (Dort) matches, the same as "Cam"/"Cameron"
# (Johnson); a 1-char floor would let initials false-positive-match everyone
_MIN_FALLBACK_FIRST_NAME_CHARS = 2


def _name_parts(normalized_name: str) -> tuple[str, str] | None:
    """(first, last) token split of an already-normalize_name'd name; None
    when there's no separate first/last token to split (a single-word name
    has nothing for the alias fallback below to compare)."""
    tokens = normalized_name.split()
    if len(tokens) < 2:
        return None
    return tokens[0], tokens[-1]


def _first_names_alias(a: str, b: str) -> bool:
    """True when one first name is a prefix of the other (nickname-style:
    "cam"/"cameron", "lu"/"luguentz"), long enough to not be a coincidence."""
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= _MIN_FALLBACK_FIRST_NAME_CHARS and longer.startswith(shorter)


def _alias_fallback_rank(
    requested_name: str, rank_map: dict[str, int], claimed: set[str]
) -> int | None:
    """A list entry's rank for `requested_name` via a same-last-name,
    nickname-prefix-first-name match, when normalize_name's exact match
    missed it (e.g. a list's "Cam Johnson" for a requested "Cameron
    Johnson"). Only fires when exactly one list entry qualifies and that
    entry isn't already the exact-match target of some other requested
    player in this same list -- ambiguity (0 or 2+ candidates, or a claimed
    entry) resolves to "no match" (falls through to the normal imputation
    path) rather than guessing wrong.
    """
    parts = _name_parts(requested_name)
    if parts is None:
        return None
    first, last = parts

    candidates = [
        key
        for key in rank_map
        if key not in claimed
        and (key_parts := _name_parts(key)) is not None
        and key_parts[1] == last
        and _first_names_alias(first, key_parts[0])
    ]
    return rank_map[candidates[0]] if len(candidates) == 1 else None


def consensus_ranks(
    lists: list[ConsensusList], player_names: list[str], settings: Settings
) -> dict[str, ConsensusResult]:
    """Weighted-average each requested player's rank across all consensus lists.

    A list that omits a player is not skipped -- silently dropping it would
    bias the average toward whichever short lists happen to include the
    player -- instead it contributes an imputed rank of (list length +
    imputation_penalty), flagged so callers can tell real ranks from filled-in ones.
    """
    normalized_requested = {normalize_name(name) for name in player_names}

    # precompute each list's normalized-name -> rank map, its source weight,
    # and which of its entries are already an exact-match target for some
    # requested player (off-limits to the alias fallback below) once
    list_rank_maps = []
    for lst in lists:
        rank_map = {normalize_name(n): idx + 1 for idx, n in enumerate(lst.players)}
        claimed = set(rank_map) & normalized_requested
        list_rank_maps.append((lst, rank_map, _source_weight(lst.source, settings), claimed))

    results: dict[str, ConsensusResult] = {}
    for name in normalized_requested:
        # resolve each list's match for this name once: exact normalize_name
        # match first, then the alias fallback (only tried when there's no
        # exact match) -- done per-name (not precomputed once for every list)
        # so "appears anywhere" reflects alias matches too, not just exact
        # ones; a name that only matches under a nickname in one list must
        # not be treated as unmentioned everywhere
        per_list: list[tuple[ConsensusList, float, int | None, bool]] = []
        matched_anywhere = False
        for lst, rank_map, weight, claimed in list_rank_maps:
            if name in rank_map:
                per_list.append((lst, weight, rank_map[name], False))
                matched_anywhere = True
                continue
            fallback_rank = _alias_fallback_rank(name, rank_map, claimed)
            if fallback_rank is not None:
                per_list.append((lst, weight, fallback_rank, False))
                matched_anywhere = True
            else:
                per_list.append((lst, weight, None, True))  # rank computed below (needs lst.players' len)

        if not matched_anywhere:
            # never mentioned by any source (exact or alias) -- nothing to
            # average, nothing to impute
            results[name] = ConsensusResult(None, 0, None, {})
            continue

        weighted_sum = 0.0
        weight_total = 0.0
        sources_used = 0
        per_source: dict[str, dict[str, int | bool]] = {}
        real_entries: list[tuple[int, float]] = []  # (rank, weight) for variance, real only

        for lst, weight, rank, imputed in per_list:
            if imputed:
                rank = len(lst.players) + settings.consensus.imputation_penalty
            else:
                sources_used += 1
                real_entries.append((rank, weight))  # type: ignore[arg-type]

            # imputed ranks still count toward the weighted average (see docstring)
            weighted_sum += weight * rank  # type: ignore[operator]
            weight_total += weight
            per_source[lst.source.source] = {"rank": rank, "imputed": imputed}

        consensus_rank = weighted_sum / weight_total if weight_total else None

        # variance measures how much the *real* sources disagree; a lone real
        # source has nothing to disagree with, so its variance is 0.0
        if len(real_entries) <= 1:
            rank_variance = 0.0
        else:
            real_weight_total = sum(w for _, w in real_entries)
            real_mean = sum(r * w for r, w in real_entries) / real_weight_total
            rank_variance = (
                sum(w * (r - real_mean) ** 2 for r, w in real_entries) / real_weight_total
            )

        results[name] = ConsensusResult(consensus_rank, sources_used, rank_variance, per_source)

    return results


def disagreement(
    model_rank: int,
    consensus_rank: float | None,
    rank_variance: float | None,
    settings: Settings,
) -> Disagreement:
    if consensus_rank is None:
        return Disagreement(None, "no_consensus")

    # positive = model likes the player more than consensus (lower model rank number)
    rank_difference = consensus_rank - model_rank
    threshold = settings.consensus.disagreement_rank_threshold

    # uncertainty is checked first: a noisy consensus shouldn't be trusted
    # enough to call the model either right (loves) or wrong (fades)
    if rank_variance is not None and rank_variance > settings.consensus.high_variance_threshold:
        flag = "high_uncertainty"
    elif rank_difference >= threshold:
        flag = "model_loves"
    elif rank_difference <= -threshold:
        flag = "model_fades"
    else:
        flag = "none"

    return Disagreement(rank_difference, flag)
