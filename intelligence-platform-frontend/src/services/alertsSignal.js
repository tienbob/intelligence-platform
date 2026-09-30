// Minimal cross-component signal for alert mutations.
//
// Alerts.jsx notifies after create/dismiss; TopNav listens so the unread
// badge updates immediately — previously the badge was fetched once per
// authentication change and stayed stale for the whole session (audit F03).
const EVENT_NAME = 'mi:alerts-changed';

export function notifyAlertsChanged() {
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function onAlertsChanged(handler) {
  window.addEventListener(EVENT_NAME, handler);
  return () => window.removeEventListener(EVENT_NAME, handler);
}
