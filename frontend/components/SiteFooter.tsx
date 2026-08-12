import Link from "next/link";
import YahooAttribution from "./YahooAttribution";

// shared chrome — reused as-is once the dashboard exists, so keep this
// component free of any landing-page-specific copy or state.
export default function SiteFooter() {
  return (
    <footer className="border-t-2 border-ink">
      <div className="mx-auto flex max-w-4xl flex-col gap-4 px-6 py-8 sm:px-10">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <YahooAttribution />
          <nav aria-label="Legal" className="flex gap-6">
            <Link
              href="/privacy"
              className="font-mono text-xs uppercase tracking-wide text-ink/70 underline decoration-rule underline-offset-4 hover:text-ink hover:decoration-ink"
            >
              Privacy
            </Link>
            <Link
              href="/terms"
              className="font-mono text-xs uppercase tracking-wide text-ink/70 underline decoration-rule underline-offset-4 hover:text-ink hover:decoration-ink"
            >
              Terms
            </Link>
          </nav>
        </div>
        <p className="font-mono text-[0.65rem] text-ink/80">
          NineCat is not affiliated with or endorsed by Yahoo or the NBA.
        </p>
      </div>
    </footer>
  );
}
