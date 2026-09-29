import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getMarketOverview, getAlerts, getMarketIndices, getTopMovers } from '../services/api';
import { useToast } from '../components/Toast';
import { REFRESH_DASHBOARD_MS } from '../config';

export default function Dashboard() {
  const toast = useToast();
  const navigate = useNavigate();
  const [market, setMarket] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [indices, setIndices] = useState([]);
  const [topMovers, setTopMovers] = useState([]);

  const loadData = useCallback(async () => {
    // Fire each request independently so every section renders as soon as its
    // own response returns — a slow/failing one (e.g. rate-limited indices)
    // never blocks the others.
    getMarketOverview()
      .then(setMarket)
      .catch(() => setMarket(null));

    getAlerts({ limit: 5 })
      .then((d) => setAlerts(d?.alerts || []))
      .catch(() => setAlerts([]));

    getMarketIndices()
      .then((d) => setIndices(d?.indices || []))
      .catch(() => setIndices([]));

    getTopMovers()
      .then((d) => setTopMovers(d?.top_movers || []))
      .catch(() => setTopMovers([]));
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData();
    }, 0);
    const interval = REFRESH_DASHBOARD_MS > 0 ? setInterval(loadData, REFRESH_DASHBOARD_MS) : null;
    return () => {
      clearTimeout(timer);
      if (interval) clearInterval(interval);
    };
  }, [loadData]);

  const trend = market?.market?.trend || '—';
  const volatility = market?.market?.volatility || '—';
  const vix = market?.macro_environment?.vix || '—';
  const vixPct = market?.macro_environment?.vix ? Math.min(100, (market.macro_environment.vix / 40) * 100) : 45;

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Market Dashboard</h1>
          <p className="text-sm text-on-surface-variant mt-1">Real-time overview & macro intelligence.{REFRESH_DASHBOARD_MS > 0 ? ` Auto-refreshes every ${REFRESH_DASHBOARD_MS / 1000}s.` : ''}</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary flex items-center gap-2" onClick={() => toast('Export feature coming soon', 'info')}>
            <span className="material-symbols-outlined text-sm">download</span> Export
          </button>
          <button className="btn-primary flex items-center gap-2" onClick={() => navigate('/alerts')}>
            <span className="material-symbols-outlined text-sm">add</span> New Alert
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-gutter">
        {/* Macro Snapshot */}
        <div className="md:col-span-4 card flex flex-col">
          <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
            <span className="material-symbols-outlined text-tertiary">query_stats</span>
            Macro Snapshot
          </h3>
          <div className="flex-1 flex flex-col justify-center gap-6">
            <div className="flex justify-between items-end">
              <div>
                <p className="text-xs text-on-surface-variant mb-1 uppercase tracking-wider">Trend Indicator</p>
                <p className="text-2xl font-semibold text-tertiary flex items-center gap-1">
                  {trend === 'bullish' ? 'Bullish' : trend === 'bearish' ? 'Bearish' : trend}
                  {trend === 'bullish' && <span className="material-symbols-outlined text-sm">trending_up</span>}
                </p>
              </div>
            </div>
            <div className="flex justify-between items-end mt-2">
              <div>
                <p className="text-xs text-on-surface-variant mb-1 uppercase tracking-wider">Market Volatility</p>
                <p className="text-2xl font-semibold text-secondary flex items-center gap-1">{volatility}</p>
              </div>
              <div className="text-right">
                <p className="text-sm text-on-surface data-font">VIX: {vix}</p>
              </div>
            </div>
            <div className="w-full bg-surface-variant h-2 rounded-full overflow-hidden">
              <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${vixPct}%` }} />
            </div>
          </div>
        </div>

        {/* Major Indices */}
        <div className="md:col-span-8 card flex flex-col">
          <h3 className="text-lg font-semibold text-on-surface mb-4 border-b border-outline-variant pb-2">
            Major Indices
          </h3>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 flex-1">
            {indices.length > 0 ? (
              indices.map((idx) => (
                <div key={idx.name} className="bg-surface-variant rounded p-3 border border-outline-variant flex flex-col justify-between hover:border-secondary transition-colors cursor-pointer group">
                  <p className="text-xs text-on-surface-variant group-hover:text-on-surface transition-colors">{idx.name}</p>
                  <p className="text-base font-medium text-on-surface mt-2 data-font">
                    {idx.price?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </p>
                  <p className={`text-sm mt-1 flex items-center gap-1 data-font ${(idx.change_percent || 0) >= 0 ? 'text-tertiary' : 'text-error'}`}>
                    {(idx.change_percent || 0) >= 0 ? '+' : ''}{idx.change_percent?.toFixed(2)}%
                    <span className="material-symbols-outlined text-xs">{(idx.change_percent || 0) >= 0 ? 'arrow_upward' : 'arrow_downward'}</span>
                  </p>
                </div>
              ))
            ) : (
              <div className="col-span-4 py-8 text-center text-on-surface-variant">
                <span className="material-symbols-outlined text-4xl mb-2 block">show_chart</span>
                <p>Index data unavailable. Provider may be offline.</p>
              </div>
            )}
          </div>
        </div>

        {/* Top Movers */}
        <div className="md:col-span-8 card flex flex-col overflow-hidden !p-0">
          <div className="p-widget-padding border-b border-outline-variant flex justify-between items-center bg-surface-container-low sticky top-0 z-10">
            <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2">
              Top Movers
            </h3>
            <button className="text-primary text-sm font-semibold hover:underline" onClick={() => navigate('/market')}>View Full Table</button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-container-highest border-b border-outline-variant">
                  <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Ticker</th>
                  <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Price</th>
                  <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Change %</th>
                  <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Volume</th>
                  <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="text-sm data-font text-on-surface">
                {topMovers.length > 0 ? (
                  topMovers.map((row, i) => (
                    <tr key={row.ticker} className={`${i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'} border-b border-outline-variant hover:bg-surface-variant transition-colors group`}>
                      <td className="py-2 px-4 font-bold flex items-center gap-2">
                        <div className="w-6 h-6 rounded bg-primary-container text-primary flex items-center justify-center text-xs data-font">{row.ticker[0]}</div>
                        {row.ticker}
                      </td>
                      <td className="py-2 px-4">${row.price?.toFixed(2)}</td>
                      <td className={`py-2 px-4 ${row.up ? 'text-tertiary' : 'text-error'}`}>
                        {row.up ? '+' : ''}{row.change_percent?.toFixed(2)}%
                      </td>
                      <td className="py-2 px-4 text-on-surface-variant">{(row.volume / 1e6).toFixed(1)}M</td>
                      <td className="py-2 px-4 text-right">
                        <button className="text-secondary opacity-0 group-hover:opacity-100 transition-opacity" onClick={() => navigate(`/companies/${row.ticker}`)}>
                          <span className="material-symbols-outlined text-sm">swap_horiz</span>
                        </button>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr><td colSpan={5} className="py-8 text-center text-on-surface-variant">No top movers data available.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Alerts & Quick Links */}
        <div className="md:col-span-4 flex flex-col gap-gutter">
          <div className="card flex-1">
            <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
              <span className="material-symbols-outlined text-error">warning</span>
              Market Alerts
            </h3>
            <div className="space-y-3">
              {alerts.length > 0 ? (
                alerts.map((alert) => (
                  <div key={alert.id} className={`p-3 bg-surface-variant border rounded flex items-start gap-3 ${alert.severity === 'high' ? 'border-error-container' : 'border-outline-variant'}`}>
                    <span className={`material-symbols-outlined text-lg mt-0.5 ${alert.severity === 'high' ? 'text-error' : 'text-secondary'}`}>
                      {alert.severity === 'high' ? 'trending_down' : 'notifications_active'}
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-on-surface">{alert.ticker || 'System'} Alert</p>
                      <p className="text-xs text-on-surface-variant mt-1">{alert.message}</p>
                      <p className="text-xs text-on-surface-variant mt-2 data-font">{alert.alert_type}</p>
                    </div>
                  </div>
                ))
              ) : (
                <div className="p-3 bg-surface-variant border border-outline-variant rounded flex items-start gap-3">
                  <span className="material-symbols-outlined text-secondary text-lg mt-0.5">notifications_active</span>
                  <div>
                    <p className="text-sm font-semibold text-on-surface">No Active Alerts</p>
                    <p className="text-xs text-on-surface-variant mt-1">System monitoring is active.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
          <div className="card">
            <h3 className="text-lg font-semibold text-on-surface mb-3">Quick Links</h3>
            <div className="grid grid-cols-2 gap-2">
              <Link className="p-3 bg-surface-variant border border-outline-variant rounded flex flex-col items-center justify-center gap-2 hover:bg-surface-bright hover:border-secondary transition-colors group text-center" to="/analysis">
                <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary">monitoring</span>
                <span className="text-xs text-on-surface">Deep Analysis</span>
              </Link>
              <Link className="p-3 bg-surface-variant border border-outline-variant rounded flex flex-col items-center justify-center gap-2 hover:bg-surface-bright hover:border-secondary transition-colors group text-center" to="/opportunities">
                <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary">insights</span>
                <span className="text-xs text-on-surface">Opportunities</span>
              </Link>
              <Link className="p-3 bg-surface-variant border border-outline-variant rounded flex flex-col items-center justify-center gap-2 hover:bg-surface-bright hover:border-secondary transition-colors group text-center col-span-2" to="/news">
                <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary">newspaper</span>
                <span className="text-xs text-on-surface">News Aggregator</span>
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}