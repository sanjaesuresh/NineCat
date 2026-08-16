"use client";

import { useId, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { captionClasses, controlClasses, headingClasses, proseClasses, uiTextClasses } from "@/components/dashboard/layout/typography";
import { noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";

/**
 * Accessible confirm dialog built on native <dialog> — showModal() gives us
 * focus containment and Escape-to-close for free, so no custom focus-trap
 * code is needed. Optionally requires typing an exact phrase before the
 * confirm action becomes available (used for account deletion).
 */
export default function ConfirmDialog({
  triggerLabel,
  triggerClassName,
  title,
  description,
  confirmLabel,
  pendingLabel = "Working…",
  requirePhrase,
  danger = false,
  onConfirm,
}: {
  triggerLabel: string;
  triggerClassName: string;
  title: string;
  description: string;
  confirmLabel: string;
  pendingLabel?: string;
  requirePhrase?: string;
  danger?: boolean;
  onConfirm: () => Promise<void>;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  // two ConfirmDialogs can be mounted on the same page (disconnect + delete on
  // settings) — a hardcoded id would make the second dialog's title announce
  // the first's, since aria-labelledby resolves by id, not by DOM proximity
  const titleId = useId();
  const descriptionId = useId();
  const [typedPhrase, setTypedPhrase] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function open() {
    setError(null);
    setTypedPhrase("");
    dialogRef.current?.showModal();
  }

  function close() {
    if (pending) return; // don't let a stray Escape abandon an in-flight request
    dialogRef.current?.close();
  }

  async function handleConfirm() {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      // caller navigates away on success (redirect to "/"); nothing left to reset here
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `That didn't go through (${err.status}). Try again.`
          : "That didn't go through. Check your connection and try again.",
      );
      setPending(false);
    }
  }

  const phraseSatisfied = !requirePhrase || typedPhrase === requirePhrase;

  return (
    <>
      <button type="button" onClick={open} className={triggerClassName}>
        {triggerLabel}
      </button>
      <dialog
        ref={dialogRef}
        onCancel={(e) => {
          if (pending) e.preventDefault();
        }}
        onClick={(e) => {
          if (e.target === dialogRef.current) close();
        }}
        className="w-full max-w-md border-2 border-ink bg-paper p-6 text-ink backdrop:bg-ink/40"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <h2 id={titleId} className={headingClasses()}>
          {title}
        </h2>
        <p id={descriptionId} className={`mt-2 ${proseClasses()}`}>
          {description}
        </p>

        {requirePhrase && (
          <label className="mt-4 block">
            <span className={captionClasses()}>
              Type {requirePhrase} to confirm
            </span>
            <input
              type="text"
              value={typedPhrase}
              onChange={(e) => setTypedPhrase(e.target.value)}
              autoComplete="off"
              className={`mt-1 w-full border border-ink bg-paper px-3 py-2 ${uiTextClasses()}`}
            />
          </label>
        )}

        {error && (
          <p role="alert" className={`mt-3 ${noticeClasses()} ${proseClasses()}`}>
            <span className={noticeDotClasses("error")} aria-hidden="true" />
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-3">
          <button
            type="button"
            onClick={close}
            disabled={pending}
            className={`border border-ink px-3 py-1.5 hover:bg-ink hover:text-paper disabled:opacity-60 ${controlClasses()}`}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={pending || !phraseSatisfied}
            className={`border px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-60 ${controlClasses()} ${
              danger
                ? "border-alert hover:bg-alert hover:text-paper"
                : "border-ink hover:bg-ink hover:text-paper"
            }`}
          >
            {pending ? pendingLabel : confirmLabel}
          </button>
        </div>
      </dialog>
    </>
  );
}
