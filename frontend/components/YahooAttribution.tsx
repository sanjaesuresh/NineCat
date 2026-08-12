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
      className="font-mono text-xs text-ink/70 underline decoration-rule underline-offset-4 hover:text-ink hover:decoration-ink"
    >
      Fantasy data provided by Yahoo Fantasy
    </a>
  );
}
