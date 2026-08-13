// TODO(branding): Yahoo's fantasy sports API terms require displaying their
// official "Fantasy Sports powered by Yahoo" logo asset unmodified alongside
// this attribution. Get the current mark from Yahoo's developer branding
// guidelines and render it next to (not instead of) this text link — do not
// redraw or approximate the logo. Text-only attribution is a placeholder
// until that asset is added under public/.
export default function YahooAttribution() {
  return (
    <a
      href="https://sports.yahoo.com/fantasy"
      target="_blank"
      rel="noopener noreferrer"
      // matches the footer's Privacy/Terms link ramp (condensed, bold,
      // uppercase, same size, same border-bottom hover) so this legally
      // required link reads as part of the same row instead of a mismatched
      // third element — inline-flex + py-1.5 keeps its hit area >=24px
      className="inline-flex items-center border-b-2 border-transparent py-1.5 font-condensed text-sm font-bold uppercase tracking-[0.05em] no-underline transition-colors hover:border-red-ink hover:text-gold focus-visible:border-red-ink focus-visible:text-gold"
    >
      Fantasy data provided by Yahoo Fantasy
    </a>
  );
}
