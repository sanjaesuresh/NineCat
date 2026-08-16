import type { ReactNode } from "react";
import { panelClasses, panelHeadingId } from "./layoutTokens";
import { captionClasses, headingClasses } from "./typography";

/**
 * Shared section shell for every dashboard panel: a header strip (title +
 * optional right-aligned meta) above arbitrary children. The section's
 * accessible name comes from aria-labelledby pointing at the heading below,
 * not from a redundant aria-label. Table accessible names are unrelated --
 * each table owns its name via its own <caption> (see BuildProfile.tsx) --
 * but the heading's `id` itself is an e2e-critical contract: existing
 * Playwright specs (adds.spec.ts, matchup.spec.ts, draft.spec.ts) locate
 * panels by literal heading id, e.g. `#punt-heading`, not by accessible
 * name. `headingId` defaults to a title-derived slug but must be overridable
 * so a page rebuilt on Panel can keep matching those pre-existing ids.
 */
export default function Panel({
  title,
  meta,
  flush,
  tone = "default",
  className,
  headingId,
  children,
}: {
  /** Header label; also the source of the section's accessible name. */
  title: string;
  /** Optional content right-aligned in the header strip (e.g. a count, a filter). */
  meta?: ReactNode;
  /** True when a child (e.g. a table) should run flush to the panel's border instead of getting the panel's own inner padding. */
  flush?: boolean;
  /** "default" (hairline border) or "destructive" (alert-red border), e.g.
   * Settings' delete-account panel. See layoutTokens.ts's panelClasses. */
  tone?: "default" | "destructive";
  className?: string;
  /** Overrides the default title-derived heading id, e.g. to match an
   * existing e2e locator (`#punt-heading`) that predates this component. */
  headingId?: string;
  children: ReactNode;
}) {
  const resolvedHeadingId = headingId ?? panelHeadingId(title);

  return (
    <section
      aria-labelledby={resolvedHeadingId}
      className={[panelClasses({ flush, tone }), className].filter(Boolean).join(" ")}
    >
      {/* flush panels have no inner padding on the section itself, so the
          header strip carries its own horizontal/top padding to match the
          panel's standard 16px inset; non-flush panels already get that
          inset from the section, so the header only needs the gap below it */}
      <div
        className={`flex items-baseline justify-between gap-3 border-b border-rule pb-2.5 ${
          flush ? "px-5 pt-5" : "mb-4"
        }`}
      >
        {/* sentence-case 18px condensed, not the old 12px uppercase mono: a
            panel title is the top of the local hierarchy and now carries that
            with size instead of borrowing it from shouting */}
        <h2 id={resolvedHeadingId} className={headingClasses()}>
          {title}
        </h2>
        {meta && <div className={captionClasses()}>{meta}</div>}
      </div>
      {children}
    </section>
  );
}
