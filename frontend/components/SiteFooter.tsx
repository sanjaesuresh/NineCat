import Link from "next/link";
import YahooAttribution from "./YahooAttribution";
import { SOURCE_NAME, SOURCE_SEASON, SOURCE_URL } from "@/lib/hashtagPool";

const FOOTER_LINKS = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
];

// inline-flex + py-1.5 pads each link's hit area to a ~24px target (WCAG 2.2
// 2.5.8), same pattern as Sidebar's linkClass and MastheadNav's linkClass
const footerLinkClass =
  "inline-flex items-center border-b-2 border-transparent py-1.5 no-underline transition-colors hover:border-red-ink hover:text-gold focus-visible:border-red-ink focus-visible:text-gold";

// shared chrome — reused as-is on the dashboard too, so keep this component
// free of any landing-page-specific copy or state. matches the mockup's
// ink-fill footer: wordmark + links row, then a fine-print row.
export default function SiteFooter() {
  return (
    <footer className="bg-ink-fill text-cream">
      {/* top accent stripe, purely decorative — mirrors the header's rule band */}
      <div className="h-1.5 bg-alert-fill" aria-hidden="true" />
      <div className="mx-auto max-w-6xl px-6 pt-11 pb-[30px] sm:px-10">
        <div className="flex flex-wrap items-start justify-between gap-[30px] border-b border-rule pb-6">
          <span className="font-display text-[26px] leading-none uppercase">
            NINE<span className="text-red-ink">CAT</span>
          </span>
          {/* named for its contents now that it holds Privacy/Terms plus the
              Yahoo attribution link, not just internal nav */}
          <nav aria-label="Legal and attribution">
            <ul className="flex flex-wrap items-center gap-[22px] font-condensed text-sm font-bold uppercase tracking-[0.05em]">
              {FOOTER_LINKS.map(({ href, label }) => (
                <li key={href}>
                  <Link href={href} className={footerLinkClass}>
                    {label}
                  </Link>
                </li>
              ))}
              {/* legally required Yahoo attribution — kept as its own component
                  (now restyled to match the links above), see YahooAttribution.tsx */}
              <li>
                <YahooAttribution />
              </li>
            </ul>
          </nav>
        </div>
        <div className="mt-5 flex flex-wrap justify-between gap-5 font-body text-[13px] text-cream/70">
          <span>NineCat is not affiliated with or endorsed by Yahoo or the NBA.</span>
          <span>
            Player stat lines:{" "}
            <a
              href={SOURCE_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gold underline"
            >
              {SOURCE_NAME}
            </a>{" "}
            {SOURCE_SEASON} per‑game projections, shown for demonstration.
          </span>
        </div>
      </div>
    </footer>
  );
}
