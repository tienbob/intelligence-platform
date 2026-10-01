import { useState, useEffect, useCallback, useRef } from 'react';
import { getAlerts, createAlert, markAlertRead } from '../services/api';
import { notifyAlertsChanged } from '../services/alertsSignal';
import { useToast } from '../components/Toast';
import StatusChip from '../components/StatusChip';
import Pagination from '../components/Pagination';

export default function Alerts() {
  const toast = useToast();
  const version = useRef(0);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState(null);
  // Explicit Unread/All view: dismissal writes is_read=true server-side, so
  // reloading the unread feed keeps dismissed rows hidden instead of
  // resurrecting them (audit F03).
  const [view, setView] = useState('unread');
  const [showCreate, setShowCreate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    ticker: '',
    alert_type: 'price_alert',
    severity: 'medium',
    message: '',
  });

  const loadAlerts = useCallback(async () => {
    const current = ++version.current;
    setLoading(true);
    try {
      const params = { limit: 51, offset: page * 50 };
      if (view === 'unread') params.unread_only = true;
      const data = await getAlerts(params);
      if (current !== version.current) return;
      setAlerts((data?.alerts || []).slice(0, 50));
      setHasMore((data?.alerts || []).length > 50);
      setError(null);
    } catch (e) {
      if (current === version.current) { setHasMore(false); setError(e.message || 'Failed to load alerts'); }
    } finally { if (current === version.current) setLoading(false); }
  }, [view, page]);

  const invalidateRequests = useCallback(() => { version.current++; }, []);
  useEffect(() => { loadAlerts(); return invalidateRequests; }, [loadAlerts, invalidateRequests]);

  async function handleDismiss(alert) {
    if (!alert?.can_manage) return;
    try {
      await markAlertRead(alert.id);
      setAlerts((prev) => prev.filter((a) => a.id !== alert.id));
      // Keep the TopNav unread badge consistent with the feed (audit F03).
      notifyAlertsChanged();
      await loadAlerts();
      toast('Alert dismissed', 'success');
    } catch {
      toast('Failed to dismiss alert', 'error');
    }
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!form.message.trim()) return;
    setSubmitting(true);
    try {
      const body = {
        ticker: form.ticker.trim() || null,
        alert_type: form.alert_type,
        severity: form.severity,
        message: form.message.trim(),
      };
      await createAlert(body);
      toast('Alert created', 'success');
      setForm({ ticker: '', alert_type: 'price_alert', severity: 'medium', message: '' });
      setShowCreate(false);
      notifyAlertsChanged();
      await loadAlerts();
    } catch (err) {
      toast(err.message || 'Failed to create alert', 'error');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Alerts</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            System alerts, price anomalies, and risk notifications.
          </p>
        </div>
        <div className="flex gap-2">
          <div role="group" aria-label="Alert view" className="flex rounded border border-outline-variant overflow-hidden">
            {['unread', 'all'].map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={view === option}
                className={`px-3 py-2 text-xs font-semibold capitalize transition-colors ${
                  view === option
                    ? 'bg-surface-container-highest text-on-surface'
                    : 'bg-surface-container-low text-on-surface-variant hover:text-on-surface'
                }`}
                onClick={() => { setView(option); setPage(0); }}
              >
                {option}
              </button>
            ))}
          </div>
          <button
            className="btn-primary flex items-center gap-2"
            onClick={() => setShowCreate(!showCreate)}
          >
            <span className="material-symbols-outlined text-sm">{showCreate ? 'close' : 'add'}</span>
            {showCreate ? 'Close' : 'New Alert'}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-6 p-4 rounded-lg border border-error/30 bg-error/5 text-sm text-error flex flex-wrap items-center justify-between gap-2">
          <p>Could not load alerts: {error}</p>
          <button className="btn-secondary btn-sm" onClick={loadAlerts}>Retry</button>
        </div>
      )}

      {/* Create Alert Form */}
      {showCreate && (
        <div className="card mb-6">
          <h3 className="text-lg font-semibold text-on-surface mb-4">Create Alert</h3>
          <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label htmlFor="alerts-ticker-optional" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Ticker (optional)</label>
              <input id="alerts-ticker-optional" name="alerts-ticker-optional"
                className="input-field uppercase data-font"
                placeholder="e.g. AAPL"
                value={form.ticker}
                onChange={(e) => setForm({ ...form, ticker: e.target.value })}
              />
            </div>
            <div>
              <label htmlFor="alerts-alert-type" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Alert Type</label>
              <select id="alerts-alert-type" name="alerts-alert-type"
                className="select-field"
                value={form.alert_type}
                onChange={(e) => setForm({ ...form, alert_type: e.target.value })}
              >
                <option value="price_alert">Price Alert</option>
                <option value="volume_anomaly">Volume Anomaly</option>
                <option value="news_alert">News Alert</option>
                <option value="sec_filing">SEC Filing</option>
                <option value="earnings">Earnings Release</option>
                <option value="risk_change">Risk Change</option>
                <option value="score_change">Score Change</option>
                <option value="portfolio_concentration">Portfolio Concentration</option>
              </select>
            </div>
            <div>
              <label htmlFor="alerts-severity" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Severity</label>
              <select id="alerts-severity" name="alerts-severity"
                className="select-field"
                value={form.severity}
                onChange={(e) => setForm({ ...form, severity: e.target.value })}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <label htmlFor="alerts-message" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Message</label>
              <textarea id="alerts-message" name="alerts-message"
                className="input-field data-font"
                placeholder="Alert description..."
                rows={3}
                value={form.message}
                onChange={(e) => setForm({ ...form, message: e.target.value })}
                required
              />
            </div>
            <div className="md:col-span-2 flex gap-2">
              <button type="submit" className="btn-primary" disabled={submitting}>
                {submitting ? 'Creating...' : 'Create Alert'}
              </button>
              <button type="button" className="btn-secondary" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="card overflow-hidden !p-0">
        <div className="p-widget-padding border-b border-outline-variant flex justify-between items-center bg-surface-container-low sticky top-0 z-10">
          <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2">
            <span className="material-symbols-outlined text-error">warning</span>
            Alert Feed
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-highest border-b border-outline-variant">
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Ticker</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Type</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Severity</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Message</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm data-font text-on-surface">
              {alerts.length > 0 ? (
                alerts.map((alert, i) => (
                  <tr
                    key={alert.id}
                    className={`${
                      i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'
                    } border-b border-outline-variant hover:bg-surface-variant transition-colors group ${
                      alert.severity === 'high' ? 'border-l-2 border-l-error' : ''
                    }`}
                  >
                    <td className="py-2 px-4 font-bold">{alert.ticker || '—'}</td>
                    <td className="py-2 px-4">
                      <StatusChip
                        status={alert.severity === 'high' ? 'bearish' : 'neutral'}
                        label={alert.alert_type}
                      />
                    </td>
                    <td className="py-2 px-4">
                      <span
                        className={
                          alert.severity === 'high'
                            ? 'text-error'
                            : alert.severity === 'medium'
                            ? 'text-secondary'
                            : 'text-on-surface-variant'
                        }
                      >
                        {alert.severity || '—'}
                      </span>
                    </td>
                    <td className="py-2 px-4 text-on-surface-variant max-w-md whitespace-normal break-words [overflow-wrap:anywhere]">
                      {alert.message || '—'}
                    </td>
                    <td className="py-2 px-4 text-right">
                      {alert.can_manage ? (
                        <button
                          className="px-2 py-1 bg-surface-container-highest border border-outline-variant hover:border-secondary hover:text-secondary text-on-surface rounded text-xs transition-colors focus-visible:outline-2 focus-visible:outline-secondary"
                          onClick={(e) => { e.stopPropagation(); handleDismiss(alert); }}
                        >
                          Dismiss
                        </button>
                      ) : (
                        <span className="text-[10px] text-on-surface-variant/70 whitespace-nowrap">Read only</span>
                      )}
                    </td>
                  </tr>
                ))
              ) : !error ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-on-surface-variant">
                    <span className="material-symbols-outlined text-4xl mb-2 block">notifications_off</span>
                    <p>{loading ? 'Loading alerts…' : error ? 'Alerts unavailable.' : 'No alerts on this page.'}</p>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <Pagination
          label="Alert pages"
          page={page}
          hasMore={hasMore}
          loading={loading}
          onPrev={() => setPage((p) => p - 1)}
          onNext={() => setPage((p) => p + 1)}
        />
      </div>
    </div>
  );
}