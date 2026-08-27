const statusConfig = {
  running: {
    bg: 'bg-secondary-container/20',
    border: 'border-secondary-container/50',
    text: 'text-secondary-fixed',
    dot: 'bg-secondary animate-pulse',
    icon: null,
  },
  queued: {
    bg: 'bg-surface-variant',
    border: 'border-outline-variant',
    text: 'text-on-surface-variant',
    dot: null,
    icon: 'schedule',
  },
  completed: {
    bg: 'bg-tertiary-fixed/10',
    border: 'border-tertiary-fixed/30',
    text: 'text-tertiary',
    dot: null,
    icon: 'check_circle',
  },
  failed: {
    bg: 'bg-error-container/20',
    border: 'border-error-container/50',
    text: 'text-error',
    dot: null,
    icon: 'error',
  },
  bullish: {
    bg: 'bg-tertiary-fixed/10',
    border: 'border-tertiary-fixed/30',
    text: 'text-tertiary',
    dot: 'bg-tertiary',
    icon: null,
  },
  bearish: {
    bg: 'bg-error-container/10',
    border: 'border-error-container/30',
    text: 'text-error',
    dot: 'bg-error',
    icon: null,
  },
  neutral: {
    bg: 'bg-surface-variant',
    border: 'border-outline-variant',
    text: 'text-on-surface-variant',
    dot: 'bg-on-surface-variant',
    icon: null,
  },
};

export default function StatusChip({ status, label, size = 'sm' }) {
  const config = statusConfig[status?.toLowerCase()] || statusConfig.neutral;
  const displayLabel = label || status;

  return (
    <span
      className={`status-chip ${config.bg} ${config.border} ${config.text} ${
        size === 'lg' ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-xs'
      }`}
    >
      {config.dot && <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />}
      {config.icon && (
        <span className="material-symbols-outlined text-xs">{config.icon}</span>
      )}
      {displayLabel}
    </span>
  );
}