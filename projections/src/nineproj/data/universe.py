"""Build the fantasy-relevant player universe from parsed SeasonLine data.

Every later scoring/projection module iterates PlayerRecord entries rather
than raw SeasonLine rows, so this is the one place that decides who counts
as "in the player pool" (current-season minutes) and what roster slots they
fill (via ninecat.engine.positions.slot_classes, shared with the backend).
"""

from __future__ import annotations

from dataclasses import dataclass

from ninecat.engine.positions import slot_classes

from nineproj.data.nba_stats import SeasonLine


@dataclass(frozen=True)
class PlayerRecord:
    player_id: int
    name: str
    team: str
    position: str | None
    slot_classes: frozenset[str]
    age: float
    seasons_available: list[str]


def build_universe(lines_by_season: dict[str, list[SeasonLine]]) -> list[PlayerRecord]:
    """PlayerRecords for every player with minutes > 0 in ANY blend season present.

    A player who sat out the latest season entirely (injury, late signing, a
    fetch that simply hasn't happened yet) but has real minutes in an older
    blend season is still a real player, not a rookie -- B1 fix: a returner
    like a torn-Achilles star must still enter the pool via their most recent
    season with real minutes; the availability model (Task 8) is what
    discounts a season-long absence, not exclusion from the universe. team/age
    (and position) come from that most-recent-with-minutes line specifically,
    so a since-traded/aged player's record reflects their last real season,
    not a stale earlier one.
    """
    if not lines_by_season:
        return []

    # newest-to-oldest so the first minutes>0 line found per player, below,
    # is always their most recent real season
    seasons_desc = sorted(lines_by_season, reverse=True)

    # seasons a player has any played-minutes data for, across every season
    # passed in -- so seasons_available reflects real history depth for the
    # baseline blend (Task 1's blend_weights) to use
    seasons_played: dict[int, list[str]] = {}
    for season, lines in lines_by_season.items():
        for line in lines:
            if line.minutes > 0:
                seasons_played.setdefault(line.player_id, []).append(season)

    # first (= most recent) minutes>0 line per player_id, plus how many
    # seasons back that line is from the newest season present (0 = the
    # newest season itself); a plain dict keeps first-write-wins semantics
    # for free as we walk newest to oldest
    latest_line_by_player: dict[int, SeasonLine] = {}
    season_offset_by_player: dict[int, int] = {}
    for offset, season in enumerate(seasons_desc):
        for line in lines_by_season[season]:
            if line.minutes > 0 and line.player_id not in latest_line_by_player:
                latest_line_by_player[line.player_id] = line
                season_offset_by_player[line.player_id] = offset

    records: list[PlayerRecord] = []
    for player_id, line in latest_line_by_player.items():
        # returner age fix: a line from N seasons back records the player's
        # age as of THAT season, not the pipeline's newest season -- extrapolate
        # forward by the season offset so every record's age lands on the same
        # reference season (the newest one present), the same reference point
        # a current player's age already is. Downstream consumers (baseline's
        # age curve, availability's age-penalty bracket, both via pipeline.py's
        # existing "+1 for next season") then land on the true 2026-27 age
        # instead of quietly understating an absent player by however many
        # seasons they missed.
        age = line.age + season_offset_by_player[player_id]
        records.append(
            PlayerRecord(
                player_id=player_id,
                name=line.name,
                team=line.team,
                position=line.position,
                slot_classes=slot_classes(line.position),
                age=age,
                seasons_available=sorted(seasons_played.get(player_id, [])),
            )
        )
    return records


def add_players(records: list[PlayerRecord], extra_records: list[PlayerRecord]) -> list[PlayerRecord]:
    """Append extra_records (evidence-backed rookies, added by a later task) without duplicating player_ids."""
    existing_ids = {record.player_id for record in records}
    merged = list(records)
    for record in extra_records:
        if record.player_id not in existing_ids:
            merged.append(record)
            existing_ids.add(record.player_id)
    return merged
