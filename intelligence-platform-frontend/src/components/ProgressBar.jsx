export default function ProgressBar({ value = 0, max = 100, color = 'secondary', showLabel = true, size = 'sm' }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const colorMap = {
    secondary: 'bg-secondary-container',
    tertiary: 'bg-tertiary',
    error: 'bg-error',
    primary: 'bg-primary',
  };
  const barColor = colorMap[color] || colorMap.secondary;
  const height = size === 'lg' ? 'h-2' : 'h-1.5';

  return (
    <div className="flex items-center gap-2 w-full">
      <div className={`${height} w-full bg-surface-variant rounded-full overflow-hidden`}>
        <div
          className={`${height} ${barColor} rounded-full transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs text-on-surface-variant data-font min-w-[2.5rem] text-right">
          {Math.round(pct)}%
        </span>
      )}
    </div>
  );
}