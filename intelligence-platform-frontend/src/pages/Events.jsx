import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getEvents } from '../services/api';
import StatusChip from '../components/StatusChip';

export default function Events() {
  const navigate = useNavigate();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tickerFilter, setTickerFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const params = { limit: 100 };
        if (tickerFilter.trim()) params.ticker = tickerFilter.trim().toUpperCase();
        if (typeFilter) params.event_type = typeFilter;
        const data = await getEvents(params);
        setEvents(data?.events || []);
      } catch (e) {
        setError(e.message || 'Failed to load events');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [tickerFilter, typeFilter]);

  function retryLoad() {
    setTickerFilter('');
    setTypeFilter('');
  }

  const eventTypes = [...new Set(events.map((e) => e.event_type).filter(Boolean))];

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Market Events</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Detected market events, signals, and materiality analysis.
          </p>
        </div>
        <div className="flex gap-2">
          <input
            className="input-field uppercase data-font w-40"
            placeholder="Filter ticker..."
            value={tickerFilter}
            onChange={(e) => setTickerFilter(e.target.value)}
          />
          <select className="select-field w-40" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">All Types</option>
            {eventTypes.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-6 p-4 rounded-lg border border-error/30 bg-error/5 text-sm text-error flex flex-wrap items-center justify-between gap-2">
          <p>Could not load events: {error}</p>
          <button className="btn-secondary btn-sm" onClick={retryLoad}>Retry</button>
        </div>
      )}

      {loading && (
        <div className="card py-20 text-center text-on-surface-variant">
          <span className="material-symbols-outlined text-4xl mb-2 block animate-pulse">bolt</span>
          <p className="text-sm">Loading events…</p>
        </div>
      )}

      {!loading && (
      <div className="card overflow-hidden !p-0">
        <div className="p-widget-padding border-b border-outline-variant flex justify-between items-center bg-surface-container-low sticky top-0 z-10">
          <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2">
            <span className="material-symbols-outlined text-secondary">bolt</span>
            Event Feed
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-highest border-b border-outline-variant">
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Ticker</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Event Type</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Date</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Impact</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Score</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Confidence</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Description</th>
              </tr>
            </thead>
            <tbody className="text-sm data-font text-on-surface">
              {events.length > 0 ? (
                events.map((e, i) => (
                  <tr
                    key={e.id}
                    onClick={() => navigate(`/events/${e.id}`)}
                    className={`${
                      i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'
                    } border-b border-outline-variant hover:bg-surface-variant transition-colors group cursor-pointer`}
                  >
                    <td className="py-2 px-4 font-bold">{e.ticker || '—'}</td>
                    <td className="py-2 px-4">
                      <StatusChip
                        status={e.impact === 'positive' ? 'bullish' : e.impact === 'negative' ? 'bearish' : 'neutral'}
                        label={e.event_type}
                      />
                    </td>
                    <td className="py-2 px-4 text-on-surface-variant">
                      {e.event_date ? new Date(e.event_date).toLocaleDateString() : '—'}
                    </td>
                    <td className="py-2 px-4">
                      <span
                        className={
                          e.impact === 'positive'
                            ? 'text-tertiary'
                            : e.impact === 'negative'
                            ? 'text-error'
                            : 'text-on-surface-variant'
                        }
                      >
                        {e.impact || '—'}
                      </span>
                    </td>
                    <td className="py-2 px-4">
                      {e.impact_score != null ? e.impact_score.toFixed(2) : '—'}
                    </td>
                    <td className="py-2 px-4">
                      {e.confidence != null ? `${(e.confidence * 100).toFixed(0)}%` : '—'}
                    </td>
                    <td className="py-2 px-4 text-on-surface-variant max-w-xs truncate">
                      {e.description || '—'}
                    </td>
                  </tr>
                ))
              ) : !error ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-on-surface-variant">
                    <span className="material-symbols-outlined text-4xl mb-2 block">bolt</span>
                    <p>No events detected yet. Events are generated from news and market data analysis.</p>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
      )}
    </div>
  );
}