export function preferenceKey(userId) {
  return userId == null ? null : `mi:company-preferences:${userId}`;
}
export function readPreferences(storage, userId) {
  const key = preferenceKey(userId);
  if (!key) return {};
  try {
    const value = JSON.parse(storage.getItem(key) || '{}');
    if (!value || Array.isArray(value) || typeof value !== 'object') return {};
    return Object.fromEntries(Object.entries(value).filter(([, p]) => p && typeof p === 'object')
      .map(([ticker, p]) => [ticker, { watched: p.watched === true, hidden: p.hidden === true }]));
  } catch { return {}; }
}
export function togglePreference(preferences, ticker, field) {
  return { ...preferences, [ticker]: { ...preferences[ticker], [field]: !preferences[ticker]?.[field] } };
}
