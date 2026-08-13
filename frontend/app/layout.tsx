import type { Metadata } from "next";
import { Anton, Barlow, Barlow_Condensed, Space_Mono } from "next/font/google";
import SiteHeader from "@/components/SiteHeader";
import SiteFooter from "@/components/SiteFooter";
import "./globals.css";

// display face: a single-weight condensed broadcast face (jersey/scoreboard
// energy) — hierarchy comes from size and tracking, not weight, since Anton
// only ships one cut
const anton = Anton({
  variable: "--font-anton",
  subsets: ["latin"],
  weight: ["400"],
});

// body face: a geometric-humanist sans with sport/civic-signage roots —
// distinct from a generic SaaS grotesque, still highly legible at small sizes
const barlow = Barlow({
  variable: "--font-barlow",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
});

// condensed face: the night-edition mockup's nav/label/table/tag face — same
// Barlow family as body copy, tighter counters so small-caps data rows and
// kickers stay legible without eating horizontal space
const barlowCondensed = Barlow_Condensed({
  variable: "--font-barlow-condensed",
  subsets: ["latin"],
  weight: ["500", "600", "700", "800", "900"],
});

// utility face: kept for tabular stat digits only (roster/build tables), where
// monospace alignment is a real functional need, not a stylistic default
const spaceMono = Space_Mono({
  variable: "--font-space-mono",
  subsets: ["latin"],
  weight: ["400", "700"],
});

export const metadata: Metadata = {
  title: "NineCat — 9-cat fantasy basketball copilot",
  description:
    "NineCat reads your Yahoo head-to-head 9-category fantasy basketball league and tells you what to do next. Read-only — it never drafts, adds, or trades for you.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${anton.variable} ${barlow.variable} ${barlowCondensed.variable} ${spaceMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <SiteHeader />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
