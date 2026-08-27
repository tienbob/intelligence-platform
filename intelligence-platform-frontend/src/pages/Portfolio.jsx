import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getOpportunities } from '../services/api';
import StatusChip from '../components/StatusChip';
import ProgressBar from '../components/ProgressBar';

function signalFor(rec) {
  const r = (rec || '').toUpperCase();
  if (['STRONG_OPPORTUNITY', 'OPPORTUNITY', 'STRONG_BUY', 'BUY'].includes(r)) {
    return { status: 'bullish', label: r === 'STRONG_OPPORTUNITY' ? 'Strong Opportunity' : r.replace(/_/g, ' ').toLowerCase() };
  }
  if (['WATCH', 'NEUTRAL', 'HOLD'].includes(r)) {
    return { status: 'neutral', label: r.charAt(0) + r.slice(1).toLowerCase() };
  }
  if (['CAUTION', 'AVOID', 'HIGH_RISK', 'SELL'].includes(r)) {
    return { status: 'bearish', label: r === 'HIGH_RISK' ? 'High Risk' : r.charAt(0) + r.slice(1).toLowerCase() };
  }
  return { status: 'neutral', label: '—' };
}

function colorFor(score) {
  if (score == null) return 'secondary';
  if (score > 60) return 'tertiary';
  if (score > 30) return 'secondary';
  return 'error';
}

export default function Portfolio() {
  const navigate = useNavigate();
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);

  async function loadOpportunities() {
    try {
      const data = await getOpportunities({ limit: 20 });
      setOpportunities(data?.opportunities || []);
    } catch {
      // API not available
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadOpportunities(); }, []);

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Investment Intelligence</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            AI-scored opportunities across the market.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button className="btn-sm btn-secondary" onClick={loadOpportunities}>Refresh</button>
          <button className="btn-sm btn-primary" onClick={() => navigate('/analysis')}>
            <span className="material-symbols-outlined text-sm">bolt</span>
            Run AI Analysis
          </button>
        </div>
      </div>

      {loading && (
        <div className="card py-20 text-center text-on-surface-variant">
          <span className="material-symbols-outlined text-4xl mb-2 block animate-pulse">insights</span>
          <p className="text-sm">Loading investment opportunities…</p>
        </div>
      )}

      {!loading && (
        <>
          {/* Investment Opportunities — the research showcase */}
          <div className="card overflow-hidden !p-0 mb-6">
            <div className="p-widget-padding border-b border-outline-variant bg-surface-container-low flex justify-between items-center">
              <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2">
                <span className="material-symbols-outlined text-tertiary">insights</span>
                AI Investment Opportunities
              </h3>
              <span className="text-xs data-font text-on-surface-variant">{opportunities.length} companies</span>
            </div>
            {opportunities.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-surface-container-highest border-b border-outline-variant">
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Ticker</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">AI Score</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Risk</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Volatility</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Sector</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold text-right">Signal</th>
                    </tr>
                  </thead>
                  <tbody className="text-sm data-font text-on-surface">
                    {opportunities.map((opp, i) => {
                      const signal = signalFor(opp.recommendation);
                      return (
                        <tr
                          key={opp.ticker}
                          onClick={() => navigate(`/companies/${opp.ticker}`)}
                          className={`${i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'} border-b border-outline-variant hover:bg-surface-variant transition-colors group cursor-pointer`}
                        >
                          <td className="py-2 px-4 font-bold">{opp.ticker}</td>
                          <td className="py-2 px-4">
                            <div className="flex items-center gap-2">
                              <ProgressBar value={opp.score || 0} max={100} color={colorFor(opp.score)} showLabel={false} />
                              <span className="text-on-surface-variant">{opp.score != null ? Number(opp.score).toFixed(0) : '—'}</span>
                            </div>
                          </td>
                          <td className="py-2 px-4">
                            <span className={opp.risk_score > 60 ? 'text-error' : opp.risk_score > 30 ? 'text-secondary' : 'text-tertiary'}>
                              {opp.risk_score != null ? Number(opp.risk_score).toFixed(0) : '—'}
                            </span>
                          </td>
                          <td className="py-2 px-4 text-secondary">
                            {opp.volatility != null ? `${(Number(opp.volatility) * 100).toFixed(1)}%` : '—'}
                          </td>
                          <td className="py-2 px-4 text-on-surface-variant">{opp.sector || 'Unknown'}</td>
                          <td className="py-2 px-4 text-right">
                            <StatusChip status={signal.status} label={signal.label} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-14 text-center text-on-surface-variant">
                <span className="material-symbols-outlined text-4xl mb-2 block">search</span>
                <p>No scored opportunities yet.</p>
                <p className="text-xs mt-1">Run AI analysis on companies, then revisit here.</p>
                <button className="btn-sm btn-primary mt-4" onClick={() => navigate('/analysis')}>Run AI Analysis</button>
              </div>
            )}
          </div>

          {/* Quick Actions */}
          <div className="card">
            <h3 className="text-lg font-semibold text-on-surface mb-3">Research</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <a href="/companies" className="p-3 bg-surface-variant border border-outline-variant rounded hover:bg-surface-bright hover:border-secondary transition-colors group block">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary">domain</span>
                  <span className="text-sm text-on-surface">Browse Companies</span>
                </div>
                <p className="text-xs text-on-surface-variant mt-1">Fundamentals, technicals, and financial metrics.</p>
              </a>
              <a href="/analysis" className="p-3 bg-surface-variant border border-outline-variant rounded hover:bg-surface-bright hover:border-secondary transition-colors group block">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-on-surface-variant group-hover:text-tertiary">memory</span>
                  <span className="text-sm text-on-surface">AI Analysis Jobs</span>
                </div>
                <p className="text-xs text-on-surface-variant mt-1">Run and monitor AI investment research pipelines.</p>
              </a>
            </div>
          </div>
        </>
      )}
    </div>
  );
}