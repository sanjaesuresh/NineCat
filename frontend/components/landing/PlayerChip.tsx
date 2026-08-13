// Small jersey-number badge reused across the four demo sections. Decorative
// only — the player's name always renders as adjacent text, so this stays
// aria-hidden rather than duplicating the name for screen readers.
export default function PlayerChip({ jersey, color }: { jersey: string; color: string }) {
  return (
    <span
      aria-hidden="true"
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 font-display text-xs"
      style={{ borderColor: color, color }}
    >
      {jersey}
    </span>
  );
}
