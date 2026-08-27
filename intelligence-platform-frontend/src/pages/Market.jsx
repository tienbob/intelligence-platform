import { useState, useEffect, useCallback } from 'react';
import { getMarketOverview, getTopMovers } from '../services/api';
import { useToast } from '../components/Toast';
import MetricTile from '../components/MetricTile';
import StatusChip from '../components/StatusChip';

export default function Market() {
  const toast = useToast();
  const [market, setMarket] = useState(null);
  const [topMovers, setTopMovers] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [overviewData, moversData] = await Promise.all([
        getMarketOverview(),
        getTopMovers(),
      ]);
      setMarket(overviewData);
      setTopMovers(moversData?.top_movers || []);
    } catch {
      // API not available
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const macro = market?.macro_environment || {};
  const mkt = market?.market || {};

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Market Overview</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Macro market snapshot, indices, and economic indicators.
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary flex items-center gap-2" onClick={loadData}>
            <span className="material-symbols-outlined text-sm">refresh</span> Refresh
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-gutter mb-6">
        <MetricTile
          label="Market Trend"
          value={mkt.trend || '—'}
          icon="trending_up"
          color="tertiary"
        />
        <MetricTile
          label="Volatility"
          value={mkt.volatility || '—'}
          icon="query_stats"
          color="secondary"
        />
        <MetricTile
          label="Risk Level"
          value={mkt.risk_level || '—'}
          icon="shield"
          color={mkt.risk_level === 'high' ? 'error' : 'tertiary'}
        />
        <MetricTile
          label="Economic Regime"
          value={mkt.economic_regime || '—'}
          icon="account_balance"
          color="secondary"
        />
      </div>

      <div className="grid grid-cols-12 gap-gutter">
        {/* Macro Environment (Span 6) */}
        <div className="col-span-12 lg:col-span-6 card">
          <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
            <span className="material-symbols-outlined text-secondary">public</span>
            Macro Environment
          </h3>
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: 'Fed Funds Rate', value: macro.fed_funds_rate != null ? `${macro.fed_funds_rate}%` : '—' },
              { label: 'Treasury 10Y', value: macro.treasury_10y != null ? `${macro.treasury_10y}%` : '—' },
              { label: 'CPI', value: macro.cpi != null ? `${macro.cpi}%` : '—' },
              { label: 'Unemployment', value: macro.unemployment_rate != null ? `${macro.unemployment_rate}%` : '—' },
              { label: 'VIX', value: macro.vix || '—' },
              { label: 'Yield Curve', value: macro.yield_curve_inverted ? 'Inverted' : 'Normal' },
            ].map((item) => (
              <div key={item.label} className="bg-surface-variant rounded p-3 border border-outline-variant">
                <p className="text-xs text-on-surface-variant mb-1">{item.label}</p>
                <p className="text-lg font-semibold text-on-surface data-font">{item.value}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Major Events (Span 6) */}
        <div className="col-span-12 lg:col-span-6 card">
          <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
            <span className="material-symbols-outlined text-tertiary">bolt</span>
            Major Events
          </h3>
          <div className="space-y-3">
            {market?.major_events?.length > 0 ? (
              market.major_events.map((event) => (
                <div
                  key={event.id}
                  className="p-3 bg-surface-variant border border-outline-variant rounded flex items-start gap-3 hover:border-secondary transition-colors cursor-pointer"
                >
                  <span
                    className={`material-symbols-outlined text-lg mt-0.5 ${
                      event.impact === 'positive' ? 'text-tertiary' : 'text-error'
                    }`}
                  >
                    {event.impact === 'positive' ? 'trending_up' : 'trending_down'}
                  </span>
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <StatusChip
                        status={event.impact === 'positive' ? 'bullish' : 'bearish'}
                        label={event.type}
                      />
                      <span className="text-xs text-on-surface-variant data-font">
                        {event.date ? new Date(event.date).toLocaleDateString() : ''}
                      </span>
                    </div>
                    <p className="text-sm text-on-surface">{event.description}</p>
                  </div>
                </div>
              ))
            ) : (
              <div className="py-12 text-center text-on-surface-variant">
                <span className="material-symbols-outlined text-4xl mb-2 block">event</span>
                <p>No major events detected.</p>
              </div>
            )}
          </div>
        </div>

        {/* Top Movers (Span 12) */}
        <div className="col-span-12 card">
          <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
            <span className="material-symbols-outlined text-primary">leaderboard</span>
            Top Movers
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {topMovers.length > 0 ? (
              topMovers.map((mover) => (
                <div
                  key={mover.ticker}
                  className="bg-surface-variant rounded p-3 border border-outline-variant hover:border-secondary transition-colors cursor-pointer"
                >
                  <div className="flex justify-between items-start mb-2">
                    <p className="text-xs text-on-surface-variant">{mover.ticker}</p>
                    <StatusChip
                      status={mover.up ? 'bullish' : 'bearish'}
                      label={`${mover.change_percent > 0 ? '+' : ''}${mover.change_percent.toFixed(2)}%`}
                    />
                  </div>
                  <p className="text-sm font-semibold text-on-surface data-font">
                    {mover.price?.toFixed(2)}
                  </p>
                  <p className="text-xs text-on-surface-variant">
                    {mover.name}
                  </p>
                </div>
              ))
            ) : (
              <div className="col-span-4 py-8 text-center text-on-surface-variant">
                <span className="material-symbols-outlined text-4xl mb-2 block">leaderboard</span>
                <p>No top movers data available.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}