import type { StreamingPlan, WeekRange } from "@/lib/api";
import { LABEL_BY_CONTRACT_KEY } from "@/components/dashboard/categoryKeys";
import { formatGamesCount } from "@/components/dashboard/format";
import { formatSlotDay, describeWindowDirection } from "./format";
import { describeReason, describeNote } from "./tokens";

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
 * The contract has no player name for a streaming candidate — these are
 * free agents, not roster players, so there's no roster row to join a name
 * from (see lib/api.ts StreamSlot; player_key is the only identifier the
 * backend has). Rendering the raw key as a labeled "Player #<key>" is honest
 * about that gap rather than inventing a name.
 */
export default function AddScheduleTable({
  streaming,
  asOf,
  weekRange,
}: {
  streaming: StreamingPlan | null;
  // asOf + weekRange let the full_week banner say WHICH direction (week not
  // started vs. week already over) rather than a direction-agnostic "not
  // live" — the backend already knows which, so the UI shouldn't drop it
  asOf: string;
  weekRange: WeekRange;
}) {
  if (!streaming) {
    return (
      <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
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
          className="mb-3 border-l-4 border-amber bg-ink/[0.03] px-3 py-2 text-sm text-ink"
        >
          {FULL_WEEK_COPY[describeWindowDirection(asOf, weekRange.start_date, weekRange.end_date)]}
        </p>
      )}

      <p className="mb-3 font-mono text-xs uppercase tracking-wide text-ink/70">
        Adds used {streaming.adds_used}
        {streaming.adds_reserved > 0 && ` · Reserved for later ${streaming.adds_reserved}`}
      </p>

      {streaming.slots.length === 0 ? (
        <div className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
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
              and stretching the page — a real past bug */}
          <div className="relative overflow-x-auto border border-rule">
            <table className="w-full min-w-[640px] border-collapse text-left">
              <caption className="sr-only">Recommended streaming adds by day</caption>
              <thead>
                <tr className="border-b-2 border-ink">
                  <th
                    scope="col"
                    className="whitespace-nowrap px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
                  >
                    Day
                  </th>
                  <th
                    scope="col"
                    className="px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
                  >
                    Player
                  </th>
                  <th
                    scope="col"
                    className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-[11px] font-normal tracking-wide text-ink/70"
                  >
                    Games added
                  </th>
                  <th
                    scope="col"
                    className="border-l border-rule px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
                  >
                    Helps
                  </th>
                  <th
                    scope="col"
                    className="border-l border-rule px-3 py-2 font-mono text-[11px] font-normal tracking-wide text-ink/70"
                  >
                    Why
                  </th>
                </tr>
              </thead>
              <tbody>
                {streaming.slots.map((slot, i) => (
                  <tr
                    key={`${slot.day}-${slot.player_key}-${i}`}
                    className="border-b border-rule last:border-b-0"
                  >
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-ink/80">
                      {formatSlotDay(slot.day)}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-ink/80">
                      Player #{slot.player_key}
                    </td>
                    <td className="whitespace-nowrap border-l border-rule px-2 py-2 text-center font-mono text-sm text-ink">
                      {formatGamesCount(slot.games_added)}
                    </td>
                    <td className="border-l border-rule px-3 py-2 text-sm text-ink">
                      {slot.categories_helped.length > 0
                        ? slot.categories_helped.map((k) => LABEL_BY_CONTRACT_KEY[k] ?? k).join(", ")
                        : "—"}
                    </td>
                    <td className="border-l border-rule px-3 py-2 text-sm text-ink">
                      {slot.reason.length > 0 ? slot.reason.map(describeReason).join("; ") : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {streaming.notes.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-ink/70">
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
