/**
 * Roster headshot cell. Falls back to a self-drawn silhouette (no external
 * asset) when headshot_url is null — decorative, since the player's name
 * already renders as text in the adjacent cell.
 */
export default function PlayerAvatar({ src }: { src: string | null }) {
  const base = "h-9 w-9 shrink-0 rounded-full border border-rule bg-ink/5 object-cover";

  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt="" aria-hidden="true" className={base} loading="lazy" />;
  }

  return (
    <svg
      className={base}
      viewBox="0 0 36 36"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="18" cy="14" r="6" fill="currentColor" className="text-ink/25" />
      <path
        d="M4 33c1.5-8 8-12 14-12s12.5 4 14 12"
        fill="currentColor"
        className="text-ink/25"
      />
    </svg>
  );
}
