import type { Metadata } from "next";
import Hero from "@/components/landing/Hero";
import DraftBoard from "@/components/landing/DraftBoard";
import MatchupSection from "@/components/landing/MatchupSection";
import WaiverColumn from "@/components/landing/WaiverColumn";
import TradeLedger from "@/components/landing/TradeLedger";

// page-level metadata overrides the root layout's title/description for "/" —
// matches the approved d-retrodata mockup's <title>/<meta name="description">
export const metadata: Metadata = {
  title: "NineCat — Every Category, Graded Like a Box Score",
  description:
    "NineCat: a 9-category fantasy basketball analytics copilot for Yahoo leagues, read like a stats-page annual.",
};

// server component: the hero's punt builder and header nav are the only client
// islands on this page, both scoped inside their own components. Each tool
// section below owns its own <section id="..."> and alternating paper/paper-2
// background per the mockup, so this file is pure composition — no wrapper
// markup or background classes to duplicate.
export default function Home() {
  return (
    <main>
      <Hero />
      <DraftBoard />
      <MatchupSection />
      <WaiverColumn />
      <TradeLedger />
    </main>
  );
}
