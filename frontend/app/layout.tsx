import type { Metadata } from "next";
import { Zilla_Slab, Source_Serif_4, Space_Mono } from "next/font/google";
import SiteHeader from "@/components/SiteHeader";
import SiteFooter from "@/components/SiteFooter";
import "./globals.css";

// display face: slab serif for the masthead and headlines — box-score personality
const zillaSlab = Zilla_Slab({
  variable: "--font-zilla-slab",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
});

// body face: a reading serif, distinct from the display slab, for paragraphs
const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
});

// utility face: stat labels, badges, category abbreviations, fine print
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
      className={`${zillaSlab.variable} ${sourceSerif.variable} ${spaceMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <SiteHeader />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
