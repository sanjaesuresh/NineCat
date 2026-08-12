// stage numbers reflect the real order these tools apply across a season
// (draft, then weekly matchups, then waivers, then trades) — not arbitrary.
export default function ToolRow({
  stage,
  name,
  status,
  description,
}: {
  stage: string;
  name: string;
  status: string;
  description: string;
}) {
  return (
    <div className="grid grid-cols-[3rem_1fr] gap-4 border-t border-rule py-6 sm:grid-cols-[3rem_1fr_auto] sm:items-baseline sm:gap-6">
      <span className="font-mono text-sm text-ink/70" aria-hidden="true">
        {stage}
      </span>
      <div>
        <h3 className="font-display text-xl font-semibold text-ink">{name}</h3>
        <p className="mt-1 max-w-prose text-ink/80">{description}</p>
      </div>
      <span className="col-span-2 mt-2 inline-flex w-fit items-center gap-2 border border-amber px-2 py-1 font-mono text-[0.65rem] uppercase tracking-wide text-ink sm:col-span-1 sm:mt-0">
        <span className="h-1.5 w-1.5 rounded-full bg-amber" aria-hidden="true" />
        {status}
      </span>
    </div>
  );
}
