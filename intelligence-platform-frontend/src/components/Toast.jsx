import { useState, createContext, useContext, useCallback } from 'react';

const ToastContext = createContext(null);

export function useToast() {
  return useContext(ToastContext);
}

let toastId = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, type = 'info') => {
    const id = ++toastId;
    setToasts((prev) => [...prev, { id, message, type }]);
    // Errors stay on screen longer — auto-dismissing everything after 3s can
    // hide the message before it's read, and every toast has a dismiss button.
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, type === 'error' ? 8000 : 3000);
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={addToast}>
      {children}
      <div role="status" aria-live="polite" aria-atomic="true" className="fixed bottom-20 md:bottom-4 right-4 max-w-[calc(100vw-2rem)] w-96 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`flex items-start gap-2 px-4 py-2 rounded text-sm font-medium shadow-lg animate-[slideIn_0.3s_ease-out] ${
              t.type === 'success'
                ? 'bg-tertiary-container text-on-tertiary-container border border-tertiary'
                : t.type === 'error'
                ? 'bg-error-container text-on-error-container border border-error'
                : 'bg-secondary-container text-on-secondary-container border border-secondary'
            }`}
          >
            <span className="flex-1 min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{t.message}</span>
            <button
              aria-label="Dismiss notification"
              className="opacity-70 hover:opacity-100 transition-opacity"
              onClick={() => dismissToast(t.id)}
            >
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
