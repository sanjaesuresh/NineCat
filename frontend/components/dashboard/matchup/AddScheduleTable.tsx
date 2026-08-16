import type { ModelExplanations, StreamingPlan, WeekRange } from "@/lib/api";
import ModelReasoning from "@/components/dashboard/advisor/ModelReasoning";
import { modelRankByItemKey, reasoningByItemKey } from "@/components/dashboard/advisor/tokens";
import { categoryLabelOrGap } from "@/components/dashboard/categoryKeys";
import { formatGamesCount } from "@/components/dashboard/format";
import { emptyStateClasses, noticeClasses, noticeDotClasses, tableRowClasses } from "@/components/dashboard/layout/layoutTokens";
import PlayerAvatar from "@/components/dashboard/PlayerAvatar";
import { formatSlotDay, describeWindowDirection } from "./format";
import { describeReason, describeNote } from "./tokens";
import {
  captionClasses,
  columnHeaderClasses,
  eyebrowClasses,
  numericClasses,
  proseClasses,
  uiTextClasses,
} from "@/components/dashboard/layout/typography";

const FULL_WEEK_COPY: Record<"before" | "after" | "unknown", string> = {
  before:
    "This week hasn't started yet, so this shows what the whole week would look like once it begins — not adds you can make today.",
  after:
    "This week has already ended, so this shows what the whole week would have looked like — not adds you can still make.",
  unknown:
    "This week isn't live right now, so this plan covers the whole week — these aren't adds you can still make today.",
};

/**
 * The add-schedule optimizer's recommended streaming slots by day.
 *
 * Slots carry the same display fields the draft board and adds list use
 * (name, position, headshot), resolved server-side from the draftable rows —
 * so a recommendation names the player rather than showing a bare id.
 */
export default function AddScheduleTable({
  streaming,
  asOf,
  weekRange,
  explanations = null,
}: {
  streaming: StreamingPlan | null;
  // optional: the table renders identically without explanations, which is
  // the default mode
  explanations?: ModelExplanations | null;
  // asOf + weekRange let the full_week banner say WHICH direction (week not
  // started vs. week already over) rather than a direction-agnostic "not
  // live" — the backend already knows which, so the UI shouldn't drop it
  asOf: string;
  weekRange: WeekRange;
}) {
  // the advisor keys a streaming slot by day AND player: the same player on
  // two different days is two separate decisions, so a player-only key would
  // collide and put one day's reasoning on the other
  const reasoningByKey = reasoningByItemKey(explanations);
  const modelRankByKey = modelRankByItemKey(explanations);

  if (!streaming) {
    return (
      <p className={emptyStateClasses()}>
        Add-schedule planning needs a known opponent so the optimizer knows which categories to
        target.
      </p>
    );
  }

  return (
    <div>
      {/* window_basis === "full_week" means the week isn't currently live (already
          over, or hasn't started) — the UI must not imply these are adds you can
          still make today */}
      {streaming.window_basis === "full_week" && (
        <p
          role="status"
          className={`mb-3 ${noticeClasses()} ${proseClasses()}`}
        >
          <span className={noticeDotClasses("warn")} aria-hidden="true" />
          {FULL_WEEK_COPY[describeWindowDirection(asOf, weekRange.start_date, weekRange.end_date)]}
        </p>
      )}

      <p className={`mb-4 ${captionClasses()}`}>
        Adds used {streaming.adds_used}
        {streaming.adds_reserved > 0 && ` · Reserved for later ${streaming.adds_reserved}`}
      </p>

      {streaming.slots.length === 0 ? (
        <div className={emptyStateClasses()}>
          {streaming.notes.length > 0 ? (
            <ul className="space-y-1">
              {streaming.notes.map((note) => (
                <li key={note}>{describeNote(note)}</li>
              ))}
            </ul>
          ) : (
            <p>No streaming adds recommended this week.</p>
          )}
        </div>
      ) : (
        <>
          {/* relative: keeps the sr-only caption clipped inside this scroll
              container instead of escaping to the initial containing block
              and stretching the page — a real past bug.
              tabIndex + named region: keyboard scroll access once the table
              overflows (WCAG 2.1.1) -- see RosterTable for the full reasoning */}
          <div
            className="relative overflow-x-auto border border-rule"
            tabIndex={0}
            role="region"
            aria-label="Recommended streaming adds by day"
          >
            <table className="w-full min-w-[640px] border-collapse text-left">
              <caption className="sr-only">Recommended streaming adds by day</caption>
              <thead>
                <tr className="border-b-2 border-ink">
                  <th
                    scope="col"
                    className={`whitespace-nowrap px-3 py-2 ${columnHeaderClasses()}`}
                  >
                    Day
                  </th>
                  <th
                    scope="col"
                    className={`px-3 py-2 ${columnHeaderClasses()}`}
                  >
                    Player
                  </th>
                  <th
                    scope="col"
                    className={`whitespace-nowrap border-l border-rule px-3 py-2 text-right ${columnHeaderClasses()}`}
                  >
                    Games added
                  </th>
                  <th
                    scope="col"
                    className={`border-l border-rule px-3 py-2 ${columnHeaderClasses()}`}
                  >
                    Helps
                  </th>
                  <th
                    scope="col"
                    className={`border-l border-rule px-3 py-2 ${columnHeaderClasses()}`}
                  >
                    Why
                  </th>
                </tr>
              </thead>
              <tbody>
                {streaming.slots.map((slot, i) => (
                  <tr
                    key={`${slot.day}-${slot.player_key}-${i}`}
                    className={tableRowClasses(i, { rowCount: streaming.slots.length })}
                  >
                    <td className={`whitespace-nowrap px-3 py-2 ${uiTextClasses("muted")}`}>
                      {formatSlotDay(slot.day)}
                    </td>
                    <td className={`px-3 py-1 ${uiTextClasses()}`}>
                      <span className="flex items-center gap-2">
                        <PlayerAvatar src={slot.headshot_url} size="sm" />
                        {/* whitespace-nowrap: without it a long name text-wraps inside
                            the flex item, blowing the row well past 36px -- every other
                            data cell here already carries this class */}
                        <span className="min-w-0 whitespace-nowrap">
                          {slot.name}
                          {slot.position ? (
                            <span className={`ml-1.5 ${eyebrowClasses()}`}>
                              {slot.position}
                            </span>
                          ) : null}
                        </span>
                      </span>
                    </td>
                    <td className={`whitespace-nowrap border-l border-rule px-3 py-2 text-right ${numericClasses()}`}>
                      {formatGamesCount(slot.games_added)}
                    </td>
                    <td className={`border-l border-rule px-3 py-2 ${uiTextClasses()}`}>
                      {slot.categories_helped.length > 0
                        ? slot.categories_helped.map(categoryLabelOrGap).join(", ")
                        : "—"}
                    </td>
                    <td className={`border-l border-rule px-3 py-2 ${uiTextClasses()}`}>
                      {slot.reason.length > 0 ? slot.reason.map(describeReason).join("; ") : "—"}
                      <ModelReasoning
                        reasoning={reasoningByKey.get(`${slot.day}:${slot.player_key}`)}
                        modelRank={modelRankByKey.get(`${slot.day}:${slot.player_key}`)}
                        engineRank={i + 1}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {streaming.notes.length > 0 && (
            <ul className={`mt-3 space-y-1 ${captionClasses()}`}>
              {streaming.notes.map((note) => (
                <li key={note}>{describeNote(note)}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
