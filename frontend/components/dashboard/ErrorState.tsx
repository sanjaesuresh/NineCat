/** Readable failure state for any ApiError that isn't a 401 (those redirect instead). */
export default function ErrorState({
  message = "Something went wrong loading this.",
  onRetry,
}: {
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="border-l-4 border-alert bg-ink/[0.03] px-4 py-4">
      <p className="text-ink">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 border border-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wide text-ink transition-colors hover:bg-ink hover:text-paper"
        >
          Try again
        </button>
      )}
    </div>
  );
}
