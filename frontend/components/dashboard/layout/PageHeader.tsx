import type { ReactNode } from "react";

/**
 * Sticky header for a dashboard page. Meant to pin to the top of a
 * scrolling main region (a later task wires the scroll container), so it
 * carries the page background so scrolled content can't show through, and
 * a bottom hairline to separate it from that content. Renders the page's
 * single h1 -- smoke.spec.ts and friends assert on level-1 headings by
 * exact name (e.g. "My Team", "Settings"), so `title` must match whatever
 * text each page used to render directly.
 */
export default function PageHeader({
  title,
  actions,
}: {
  title: string;
  /** Right-aligned controls, e.g. a refresh or filter action. */
  actions?: ReactNode;
}) {
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-rule bg-paper px-6 py-4 sm:px-10">
      <h1 className="font-display text-3xl text-ink">{title}</h1>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}
