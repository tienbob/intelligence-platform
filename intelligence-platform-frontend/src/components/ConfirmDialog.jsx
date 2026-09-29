import { useEffect, useRef } from 'react';

// Styled replacement for window.confirm: accessible alertdialog with
// Escape-to-close, click-outside-to-cancel, and focus moved to the safe
// (Cancel) action when opened.
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

  useEffect(() => {
    if (!open) return undefined;
    cancelRef.current?.focus();
    function onKey(e) {
      if (e.key === 'Escape') onCancel?.();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onCancel}
    >
      <div
        role="alertdialog"
        aria-modal="true"
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
