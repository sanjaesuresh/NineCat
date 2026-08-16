import { controlClasses } from "@/components/dashboard/layout/typography";
import { noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";
/** Readable failure state for any ApiError that isn't a 401 (those redirect instead). */
export default function ErrorState({
  message = "Something went wrong loading this.",
  onRetry,
}: {
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className={noticeClasses()}>
      <span className={noticeDotClasses("error")} aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-ink">{message}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className={`mt-3 border border-ink px-3 py-1.5 hover:bg-ink hover:text-paper ${controlClasses()}`}
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
