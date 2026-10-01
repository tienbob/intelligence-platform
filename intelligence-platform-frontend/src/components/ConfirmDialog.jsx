import { useEffect, useRef } from 'react';

// Elements that can receive focus while Tab-trapped inside the dialog.
const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Styled replacement for window.confirm: accessible alertdialog with
// Escape-to-close, click-outside-to-cancel, focus moved to the safe
// (Cancel) action when opened, Tab containment while open, and focus
// restored to the trigger on close (audit U03).
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}) {
  const cancelRef = useRef(null);
  const dialogRef = useRef(null);
  const previouslyFocused = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    previouslyFocused.current = document.activeElement;
    cancelRef.current?.focus();

    function onKey(e) {
      // While the action is running the dialog must not be dismissable — the
      // buttons are disabled, so Escape/backdrop must not race the request.
      if (busy) return;
      if (e.key === 'Escape') {
        onCancel?.();
        return;
      }
      if (e.key !== 'Tab') return;
      // Contain Tab/Shift+Tab within the dialog.
      const nodes = dialogRef.current?.querySelectorAll(FOCUSABLE);
      if (!nodes || nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      // Return focus to the trigger so keyboard users aren't dropped at the
      // top of the page.
      previouslyFocused.current?.focus?.();
    };
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={busy ? undefined : onCancel}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-busy={busy}
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        className="card max-w-md w-full bg-surface-container-low"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-dialog-title" className="text-lg font-semibold text-on-surface mb-2">
          {title}
        </h2>
        <p id="confirm-dialog-message" className="text-sm text-on-surface-variant mb-6 break-words">
          {message}
        </p>
        <div className="flex gap-2 justify-end">
          <button ref={cancelRef} className="btn-secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            className={`btn-primary ${danger ? 'bg-error-container text-on-error-container border border-error' : ''}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
