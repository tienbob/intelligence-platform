export default function MetricTile({ label, value, change, changeLabel, icon, color = 'tertiary' }) {
  const colorMap = {
    tertiary: { text: 'text-tertiary', bg: 'text-tertiary' },
    secondary: { text: 'text-secondary', bg: 'text-secondary' },
    error: { text: 'text-error', bg: 'text-error' },
    'on-surface-variant': { text: 'text-on-surface-variant', bg: 'text-on-surface-variant' },
  };
  const c = colorMap[color] || colorMap.tertiary;

  return (
    <div className="bg-surface-container border border-outline-variant/30 rounded p-widget-padding flex flex-col relative overflow-hidden group hover:border-outline-variant transition-colors">
      <div className="absolute top-0 right-0 p-3 opacity-20 group-hover:opacity-40 transition-opacity">
        <span className={`material-symbols-outlined text-5xl ${c.bg}`}>{icon}</span>
      </div>
      <span className="text-xs text-on-surface-variant mb-2">{label}</span>
      <div className="text-3xl font-bold text-on-surface mb-1 z-10 data-font">{value}</div>
      {change && (
        <div className={`flex items-center gap-1 text-xs z-10 data-font ${c.text}`}>
          <span className="material-symbols-outlined text-sm">
            {parseFloat(change) >= 0 ? 'arrow_upward' : 'arrow_downward'}
          </span>
          <span>{change}{changeLabel ? ` ${changeLabel}` : ''}</span>
        </div>
      )}
    </div>
  );
}