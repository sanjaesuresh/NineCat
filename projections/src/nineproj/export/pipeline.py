"""Pure orchestration: wire Tasks 1-13's modules into one reproducible run.

`run_pipeline` takes already-fetched data (season lines, evidence store,
schedule) and does no I/O of its own -- every fetch/cache concern lives in
run_projection.py so this stays testable against fixtures alone. Every dict
here is keyed by pid: `str(player_id)` for real NBA players, or
`"rookie-" + normalize_name(name)` for evidence-backed rookies with no NBA
history -- both are unique, hashable keys even though PlayerRecord.player_id
itself stays a bare int for veterans (the rookie string is a deliberate,
harmless type-bend of that field, matching the brief).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from ninecat.engine.positions import slot_classes

from nineproj.config import Settings
from nineproj.data.nba_stats import SeasonLine
from nineproj.data.schedule import (
    PlayoffProfile,
    Schedule,
    ScheduleUnavailable,
    UnavailableProfile,
    league_playoff_game_counts,
    playoff_profile,
)
from nineproj.data.universe import PlayerRecord, add_players, build_universe
from nineproj.models.availability import Availability, project_availability
from nineproj.models.baseline import (
    BaselineProjection,
    build_population_context,
    project_baseline,
)
from nineproj.models.environment import apply_environment, team_pace_estimates
from nineproj.models.roles import AdjustedProjection, apply_role_adjustment
from nineproj.models.rookies import RookieFlags, project_rookie
from nineproj.research.store import EvidenceStore, normalize_name
from nineproj.value.composite import CompositeResult, PlayerInputs, compute_composite
from nineproj.value.consensus import ConsensusResult, consensus_ranks
from nineproj.value.explain import Explanation, explain
from nineproj.value.ninecat import PlayerValue, value_pool
from nineproj.value.playoffs import PlayoffValue, WindowPlayoffValue, playoff_values, playoff_window_values

logger = logging.getLogger(__name__)

# rookies have zero NBA history to derive an age from; 22 lands in the <28
# bracket (0 age-penalty in availability.py) -- a neutral placeholder, not a
# fabricated real age
_ROOKIE_AGE_PLACEHOLDER = 22


def _transaction_date_key(value: str) -> tuple[int, int, int]:
    """Lenient (year, month, day) sort key for a TransactionEvent.date string.

    Accepts "YYYY", "YYYY-MM", or "YYYY-MM-DD"; a missing trailing part reads
    as 0, and an unparseable/empty date sorts earliest (0, 0, 0) rather than
    raising -- research evidence dates aren't guaranteed fully precise.
    """
    if not value:
        return (0, 0, 0)
    nums: list[int] = []
    for part in value.split("-")[:3]:
        try:
            nums.append(int(part))
        except ValueError:
            break
    nums += [0] * (3 - len(nums))
    return (nums[0], nums[1], nums[2])


@dataclass(frozen=True)
class PipelineResult:
    """Every intermediate of one run_pipeline call, keyed by pid throughout."""

    settings: Settings
    store: EvidenceStore
    projection_date: str
    schedule_available: bool
    # True when a *fetched* schedule's playoff window (weeks 19-21) has zero
    # games league-wide -- a partial/early-release NBA schedule, not a real
    # "everyone plays 0 playoff games" signal (see run_pipeline)
    playoff_window_force_unavailable: bool
    records: dict[str, PlayerRecord]  # current-team-resolved; the final "projected pool"
    old_team: dict[str, str | None]
    team_changed: dict[str, bool]
    baselines: dict[str, BaselineProjection]  # veterans only (rookies have no NBA baseline)
    adjusted: dict[str, AdjustedProjection]  # veterans + rookies, post role+environment
    rookie_flags: dict[str, RookieFlags]  # rookies only
    availabilities: dict[str, Availability]
    profiles: dict[str, PlayoffProfile | UnavailableProfile]
    # every settings.candidate_playoff_windows entry -> its own profiles/values,
    # so dataset.py can export a schedule.windows map the dashboard's dropdown
    # switches between client-side, without a pipeline re-run per window
    window_profiles: dict[tuple[int, int], dict[str, PlayoffProfile | UnavailableProfile]]
    window_values: dict[tuple[int, int], dict[str, WindowPlayoffValue]]
    values: dict[str, PlayerValue]
    playoff_values: dict[str, PlayoffValue]
    consensus: dict[str, ConsensusResult | None]
    composite: dict[str, CompositeResult]
    explanations: dict[str, Explanation]


def run_pipeline(
    settings: Settings,
    lines_by_season: dict[str, list[SeasonLine]],
    store: EvidenceStore,
    schedule: Schedule | ScheduleUnavailable,
    projection_date: str,
) -> PipelineResult:
    """Combine one season's already-fetched data into every player's full projection."""
    veteran_records = build_universe(lines_by_season)
    logger.info("stage=universe veterans=%d", len(veteran_records))

    # {player_id: {season: SeasonLine}} once, since both project_baseline and
    # project_availability need a per-player history keyed by season
    history_by_player_id: dict[int, dict[str, SeasonLine]] = {}
    for season, lines in lines_by_season.items():
        for line in lines:
            history_by_player_id.setdefault(line.player_id, {})[season] = line

    # rookies: only notes with a full evidence-backed projection get a
    # PlayerRecord at all (rookies.py's evidence-only, no-invention principle)
    rookie_adjusted: dict[str, AdjustedProjection] = {}
    rookie_flags: dict[str, RookieFlags] = {}
    rookie_records: list[PlayerRecord] = []
    for note in store.rookies:
        projected = project_rookie(note, settings)
        if projected is None:
            continue
        adjusted, flags = projected
        pid = "rookie-" + normalize_name(note.player)
        rookie_adjusted[pid] = adjusted
        rookie_flags[pid] = flags
        rookie_records.append(
            PlayerRecord(
                player_id=pid,  # str pid doubles as this record's dict key (see module docstring)
                name=note.player,
                team=note.team,
                position=note.position,
                slot_classes=slot_classes(note.position),
                age=None,  # no NBA age evidence for an unseen rookie
                seasons_available=[],
            )
        )
    logger.info("stage=rookies projected=%d notes=%d", len(rookie_records), len(store.rookies))

    merged_records = add_players(veteran_records, rookie_records)

    # current-team resolution: a player's most recent transaction with a
    # to_team overrides the team build_universe read off their most recent
    # season with real minutes; rookies have no prior team to compare
    # against, so team_changed is trivially False for them rather than
    # comparing against a fabricated one
    records_by_pid: dict[str, PlayerRecord] = {}
    old_team: dict[str, str | None] = {}
    team_changed: dict[str, bool] = {}
    for record in merged_records:
        is_rookie = isinstance(record.player_id, str)
        pid = record.player_id if is_rookie else str(record.player_id)
        if is_rookie:
            old_team[pid] = None
            team_changed[pid] = False
            records_by_pid[pid] = record
            continue

        base_team = record.team  # build_universe already read this off their most recent season line
        old_team[pid] = base_team
        # "latest" = max transaction.date (lenient-parsed; unparseable/empty
        # sorts earliest); a stable sort keeps same-date (incl. all-unparseable)
        # ties in their original encounter order, so the last of a tied group
        # wins -- matching the pre-fix behavior for that degenerate case
        dated = sorted(
            (t for t in store.transactions_for(record.name) if t.to_team is not None),
            key=lambda t: _transaction_date_key(t.date),
        )
        current_team = dated[-1].to_team if dated else base_team
        team_changed[pid] = current_team != base_team
        records_by_pid[pid] = replace(record, team=current_team) if team_changed[pid] else record

    population_context = build_population_context(lines_by_season, settings)
    pace_estimates = team_pace_estimates(lines_by_season[max(lines_by_season)]) if lines_by_season else {}

    # rookies: no prior team to compare pace against -- apply_environment's
    # None/None branch is a documented passthrough (multiplier 1.0), not a
    # special rookie case
    adjusted: dict[str, AdjustedProjection] = {
        pid: apply_environment(proj, None, None, settings) for pid, proj in rookie_adjusted.items()
    }

    baselines: dict[str, BaselineProjection] = {}
    min_sample_excluded = 0
    for record in veteran_records:
        pid = str(record.player_id)
        history = history_by_player_id.get(record.player_id, {})

        # B3: a veteran's total blend-window sample (Sigma games*minutes over
        # their actual lines, B1's zero-filled availability seasons don't
        # count here -- those are 0 minutes by definition) must clear
        # min_rankable_minutes before they're allowed to rank at all; a
        # 3-game 2.7spg cameo can't sit on the board next to a real season.
        # A returner still qualifies via their older seasons' minutes (B1).
        total_blend_minutes = sum(
            line.games * line.minutes
            for season, line in history.items()
            if season in settings.prior_seasons
        )
        if total_blend_minutes < settings.baseline.min_rankable_minutes:
            min_sample_excluded += 1
            records_by_pid.pop(pid, None)
            old_team.pop(pid, None)
            team_changed.pop(pid, None)
            continue

        baseline = project_baseline(record, history, population_context, settings)
        if baseline is None:
            # no usable prior season for this player -- excluded from the
            # whole downstream pool, not just this dict
            records_by_pid.pop(pid, None)
            old_team.pop(pid, None)
            team_changed.pop(pid, None)
            continue
        baselines[pid] = baseline
        role_adjusted = apply_role_adjustment(baseline, store.roles_for(record.name), settings)
        current_team = records_by_pid[pid].team
        old_pace = pace_estimates.get(old_team[pid]) if old_team[pid] else None
        new_pace = pace_estimates.get(current_team) if current_team else None
        adjusted[pid] = apply_environment(role_adjusted, old_pace, new_pace, settings)
    logger.info(
        "stage=baseline projected=%d skipped=%d min_sample_excluded=%d",
        len(baselines),
        len(veteran_records) - len(baselines) - min_sample_excluded,
        min_sample_excluded,
    )

    rookie_pids = set(rookie_adjusted)

    availabilities: dict[str, Availability] = {}
    for pid, record in records_by_pid.items():
        if pid in rookie_pids:
            availabilities[pid] = project_availability(
                _ROOKIE_AGE_PLACEHOLDER, {}, store.injuries_for(record.name), settings
            )
        else:
            # record.age is already extrapolated to the pipeline's newest
            # season present (build_universe's season-offset fix) -- this +1
            # still correctly lands on next season's age for both a current
            # player and a returner alike, rather than only the latter
            player_age = int(record.age) + 1  # next season's age, not this season's
            history = history_by_player_id.get(record.player_id, {})
            availabilities[pid] = project_availability(
                player_age, history, store.injuries_for(record.name), settings
            )
    logger.info("stage=availability players=%d", len(availabilities))

    # D6 no-fabrication: a schedule that fetched successfully but has zero
    # playoff-window games across the WHOLE league (not just our players'
    # teams) is a partial/early-release schedule -- normal in August, before
    # the NBA finalizes games past mid-season -- not a genuine "every team
    # has 0 playoff games" result. Treating it as unpublished (rather than
    # emitting misleadingly precise zero-game profiles/scores) redistributes
    # the playoff weight onto regular season, same as the already-tested
    # whole-schedule-unavailable path.
    # only applies to a schedule that actually fetched -- a already-unavailable
    # schedule isn't "forced" unavailable, it's just unavailable, and
    # league_playoff_game_counts returns {} for it anyway (sum 0 either way)
    league_playoff_total = sum(league_playoff_game_counts(schedule, settings).values())
    playoff_window_force_unavailable = isinstance(schedule, Schedule) and league_playoff_total == 0

    schedule_available = isinstance(schedule, Schedule) and not playoff_window_force_unavailable
    logger.info(
        "stage=schedule schedule_available=%s playoff_window_force_unavailable=%s",
        schedule_available, playoff_window_force_unavailable,
    )

    # every candidate window (dashboard dropdown) gets its own profiles, reusing
    # the exact same D6 force-unavailable decision the default window already
    # made above -- a partial/early-release schedule that nulls the default
    # window nulls every candidate window too, not just the shipped one
    default_window = (settings.playoff_window.start_week, settings.playoff_window.end_week)
    window_profiles: dict[tuple[int, int], dict[str, PlayoffProfile | UnavailableProfile]] = {}
    for candidate in settings.candidate_playoff_windows:
        if playoff_window_force_unavailable:
            window_profiles[candidate] = {pid: UnavailableProfile() for pid in records_by_pid}
        else:
            window_profiles[candidate] = {
                pid: playoff_profile(record.team, schedule, settings, window=candidate)
                for pid, record in records_by_pid.items()
            }
    profiles = window_profiles[default_window]

    values = value_pool(adjusted, availabilities, records_by_pid, settings)
    logger.info("stage=value players=%d", len(values))

    window_values: dict[tuple[int, int], dict[str, WindowPlayoffValue]] = {
        candidate: playoff_window_values(values, availabilities, window_profiles[candidate])
        for candidate in settings.candidate_playoff_windows
    }

    playoffs = playoff_values(values, availabilities, profiles, settings)
    logger.info("stage=playoff_value players=%d", len(playoffs))

    consensus_by_norm_name = consensus_ranks(
        store.consensus_lists, [record.name for record in records_by_pid.values()], settings
    )
    consensus: dict[str, ConsensusResult | None] = {
        pid: consensus_by_norm_name.get(normalize_name(record.name))
        for pid, record in records_by_pid.items()
    }
    logger.info("stage=consensus players=%d lists=%d", len(consensus), len(store.consensus_lists))

    inputs = {
        pid: PlayerInputs(
            value=values[pid],
            availability=availabilities[pid],
            playoff=playoffs[pid],
            consensus=consensus[pid],
            projection=adjusted[pid],
            rookie_flags=rookie_flags.get(pid),
        )
        for pid in records_by_pid
    }
    # H4: the imputed no-consensus rank is one worse than the single deepest
    # published list, pool-wide -- not each list's own length, since a player
    # missing everywhere should read worse than merely missing one list
    max_consensus_list_length = max(
        (len(lst.players) for lst in store.consensus_lists), default=0
    )
    composite = compute_composite(inputs, settings, max_consensus_list_length)
    logger.info("stage=composite players=%d", len(composite))

    explanations = {
        pid: explain(records_by_pid[pid].name, inputs[pid], composite[pid], settings)
        for pid in records_by_pid
    }
    logger.info("stage=explain players=%d", len(explanations))

    return PipelineResult(
        settings=settings,
        store=store,
        projection_date=projection_date,
        schedule_available=schedule_available,
        playoff_window_force_unavailable=playoff_window_force_unavailable,
        records=records_by_pid,
        old_team=old_team,
        team_changed=team_changed,
        baselines=baselines,
        adjusted=adjusted,
        rookie_flags=rookie_flags,
        availabilities=availabilities,
        profiles=profiles,
        window_profiles=window_profiles,
        window_values=window_values,
        values=values,
        playoff_values=playoffs,
        consensus=consensus,
        composite=composite,
        explanations=explanations,
    )
