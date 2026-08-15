"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// the "Draft / Matchups / Waiver / Trades" anchors only resolve on the
// landing page ("/#draft" etc.) — rendering them on any other route (e.g.
// /dashboard) would let a signed-in user click one and get bounced back to
// the marketing page. this has to be a client component (usePathname) so it
// can hide itself off "/"; SiteHeader itself stays a server component and
// just mounts this.
const NAV_LINKS = [
  { href: "/#draft", label: "Draft" },
  { href: "/#matchup", label: "Matchups" },
  { href: "/#waiver", label: "Waiver" },
  { href: "/#trade", label: "Trades" },
];

// inline-flex + py-1.5 pads each link's hit area to a ~24px target (WCAG 2.2
// 2.5.8) even though the 15px condensed text plus its 3px hover border alone
// measure well short of that — same pattern as Sidebar's linkClass
const linkClass =
  "inline-flex items-center border-b-[3px] border-transparent py-1.5 no-underline transition-colors hover:border-red-ink hover:text-red-ink focus-visible:border-red-ink focus-visible:text-red-ink";

export default function MastheadNav() {
  const pathname = usePathname();

  // landing-page-only nav: renders nothing on /dashboard, /privacy, /terms, etc.
  if (pathname !== "/") return null;

  return (
    <nav aria-label="Primary" className="max-[700px]:hidden">
      <ul className="flex gap-[22px] font-condensed text-[15px] font-bold uppercase tracking-[0.06em]">
        {NAV_LINKS.map(({ href, label }) => (
          <li key={href}>
            <Link href={href} className={linkClass}>
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
