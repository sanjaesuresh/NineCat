import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import type { CategoryKey } from "../lib/types";
import { CATEGORY_LABELS, ZSCORE_CATEGORY_ORDER } from "./charts/chartTheme";

export interface PuntBuildPickerProps {
  punts: CategoryKey[];
  onChange: (next: CategoryKey[]) => void;
}

/**
 * Single header control for the punt-build feature: a multiselect popover
 * (mirrors RankingsTable's Columns picker -- <details>/<summary>, role="button"
 * + aria-expanded, native keyboard operability) instead of two separate
 * <select>s, so there's no cap on how many categories can be punted
 * (applyPuntBuild already takes an arbitrary-length array).
 *
 * Open state is driven by an explicit onClick + preventDefault on the
 * summary rather than the native `toggle` event/onToggle: per the HTML spec
 * `toggle` fires as a queued task, not synchronously with the click, which
 * jsdom honors -- that made the popover's open state untestable (and, in a
 * real browser, one tick slower than necessary). preventDefault suppresses
 * the browser's own open/close so this is the only source of truth; Enter/
 * Space still work because browsers synthesize a click from summary key
 * activation, so keyboard operability is unaffected.
 *
 * Category order in both the button label and the checkbox list is always
 * the canonical nine-category order (not click/selection order), so the
 * label and the header's "ranked for punt X + Y build" note read
 * consistently regardless of which checkbox was toggled first or last, or
 * what order the caller's `punts` array happens to be in.
 */
export function PuntBuildPicker({ punts, onChange }: PuntBuildPickerProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDetailsElement>(null);
  const puntSet = new Set(punts);
  const orderedPunts = ZSCORE_CATEGORY_ORDER.filter((cat) => puntSet.has(cat));

  // native <details> doesn't close on Escape on its own (unlike <dialog>) --
  // wired explicitly, same pattern as PlayerDetail's Escape-to-close panel
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  // native <details> also only closes on re-toggling its own summary, not on
  // an arbitrary outside click -- close on any pointerdown outside the popover
  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open]);

  function handleSummaryClick(event: ReactMouseEvent<HTMLElement>) {
    event.preventDefault();
    setOpen((prev) => !prev);
  }

  function toggleCategory(cat: CategoryKey) {
    const next = puntSet.has(cat) ? orderedPunts.filter((c) => c !== cat) : [...orderedPunts, cat];
    onChange(ZSCORE_CATEGORY_ORDER.filter((c) => next.includes(c)));
  }

  const buttonLabel =
    orderedPunts.length === 0
      ? "Punt: none"
      : `Punt: ${orderedPunts.map((cat) => CATEGORY_LABELS[cat]).join(", ")}`;

  return (
    <details ref={containerRef} className="relative" open={open}>
      {/* see RankingsTable's Columns picker for the same role="button" +
       * aria-expanded rationale -- HTML-AAM's implicit summary->button
       * mapping isn't applied consistently by every UA/AT combination */}
      <summary
        role="button"
        aria-expanded={open}
        onClick={handleSummaryClick}
        className="min-h-[24px] cursor-pointer list-none rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm font-medium text-slate-300 hover:border-amber-400 hover:text-amber-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-amber-400"
      >
        {buttonLabel}
      </summary>
      <div className="absolute left-0 z-20 mt-2 w-48 rounded-lg border border-slate-700 bg-slate-950 p-2 shadow-lg">
        <p className="px-1 pb-1 text-xs font-medium text-slate-500">Punt build</p>
        <div className="flex flex-col gap-0.5">
          {ZSCORE_CATEGORY_ORDER.map((cat) => (
            <label
              key={cat}
              className="flex min-h-[24px] items-center gap-2 rounded px-1 py-1 text-sm text-slate-300 hover:bg-slate-800"
            >
              <input
                type="checkbox"
                checked={puntSet.has(cat)}
                onChange={() => toggleCategory(cat)}
                className="h-4 w-4 accent-amber-400"
              />
              {CATEGORY_LABELS[cat]}
            </label>
          ))}
        </div>
      </div>
    </details>
  );
}
