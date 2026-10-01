import { useState, useEffect, useCallback, Fragment } from 'react';
import { Link, useNavigate } from 'react-router-dom';
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
  // Unknown / unmapped values still render as a readable chip instead of a bare dash.
  if (r) return { status: 'neutral', label: r.charAt(0) + r.slice(1).toLowerCase().replace(/_/g, ' ') };
  return { status: 'neutral', label: '—' };
}

function colorFor(score) {
  if (score == null) return 'secondary';
  if (score > 60) return 'tertiary';
  if (score > 30) return 'secondary';
  return 'error';
}

function formatDate(value) {
  if (!value) return null;
  const d = new Date(value);
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function ScoreComponents({ opp, onNavigate }) {
  const hasAnalysis = !!opp.analysis_id;
  return (
    <div className="px-4 pb-4">
      <div className="p-4 bg-surface-container-low rounded border border-outline-variant">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-on-surface-variant uppercase tracking-wider data-font">Score components</span>
          <span className="text-[10px] text-on-surface-variant data-font">
            Screening model
            {opp.scoring_version ? ` · v${opp.scoring_version}` : ''}
            {opp.score_timestamp ? ` · ${formatDate(opp.score_timestamp)}` : ''}
          </span>
        </div>
        <div className="space-y-2">
          {opp.components?.map((c) => (
            <div key={c.label}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-on-surface-variant">{c.label}</span>
                <span className="data-font text-on-surface">{c.value != null ? c.value.toFixed(0) : '—'}</span>
              </div>
              <div className="w-full bg-surface-variant h-1.5 rounded-full overflow-hidden">
                <div className="bg-secondary h-full rounded-full" style={{ width: `${Math.min(100, c.value || 0)}%` }} />
              </div>
            </div>
          ))}
          {!opp.components?.length && (
            <p className="text-xs text-on-surface-variant">No component breakdown available for this score.</p>
          )}
        </div>
        {hasAnalysis && (
          <div className="mt-3 pt-3 border-t border-outline-variant text-[10px] text-on-surface-variant data-font flex items-center justify-between gap-3">
            <span>Deep AI Analysis</span>
            <span>
              {opp.analysis_score != null ? `score ${Number(opp.analysis_score).toFixed(1)}` : 'score —'}
              {opp.analysis_timestamp ? ` · ${formatDate(opp.analysis_timestamp)}` : ''}
            </span>
          </div>
        )}
        <div className="mt-4 pt-3 border-t border-outline-variant flex items-center justify-between gap-3">
          <div className="text-[10px] text-on-surface-variant data-font">
            {opp.scoring_model ? opp.scoring_model : 'investment_score_v1'}
          </div>
          {hasAnalysis ? (
            <button className="btn-sm btn-primary flex items-center gap-1.5" onClick={(e) => { e.stopPropagation(); onNavigate(`/analysis/${opp.analysis_id}`); }}>
              <span className="material-symbols-outlined text-sm">arrow_forward</span>
              View Deep AI Analysis
            </button>
          ) : (
            <button className="btn-sm btn-secondary flex items-center gap-1.5" onClick={(e) => { e.stopPropagation(); onNavigate('/analysis'); }}>
              <span className="material-symbols-outlined text-sm">bolt</span>
              Run AI Analysis
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Opportunities() {
  const navigate = useNavigate();
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedTicker, setExpandedTicker] = useState(null);
  const [error, setError] = useState(null);
  // `filters` holds the in-progress form values; `applied` holds what the list
  // is actually rendered with (applied via the Apply button).
  const [filters, setFilters] = useState({ min_score: '0', sector: '' });
  const [applied, setApplied] = useState({ min_score: '0', sector: '' });
  const hasActiveFilters = applied.min_score !== '0' || !!applied.sector.trim();

  const loadOpportunities = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { limit: 20 };
      if (Number(applied.min_score) > 0) params.min_score = Number(applied.min_score);
      if (applied.sector.trim()) params.sector = applied.sector.trim();
      const data = await getOpportunities(params);
      setOpportunities(data?.opportunities || []);
    } catch (e) {
      setError(e.message || 'Failed to load opportunities');
      setOpportunities([]);
    } finally {
      setLoading(false);
    }
  }, [applied]);

  useEffect(() => { loadOpportunities(); }, [loadOpportunities]);

  function applyFilters(event) {
    event.preventDefault();
    setApplied({ min_score: filters.min_score, sector: filters.sector });
  }

  function clearFilters() {
    setFilters({ min_score: '0', sector: '' });
    setApplied({ min_score: '0', sector: '' });
  }

  function toggleRow(ticker) {
    setExpandedTicker((prev) => (prev === ticker ? null : ticker));
  }

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Market Opportunities</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            AI-scored opportunities across the market.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button className="btn-sm btn-secondary" onClick={loadOpportunities}>Refresh</button>
          <Link className="btn-sm btn-primary inline-flex items-center justify-center gap-1.5" to="/analysis">
            <span aria-hidden="true" className="material-symbols-outlined text-sm leading-none shrink-0">bolt</span>
            Run AI Analysis
          </Link>
        </div>
      </div>

      {/* Filters — backed by the API's min_score / sector query params */}
      <form onSubmit={applyFilters} aria-label="Opportunity filters" className="card mb-6 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="opp-min-score" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Min AI Score</label>
          <select
            id="opp-min-score"
            className="select-field w-32"
            value={filters.min_score}
            onChange={(e) => setFilters({ ...filters, min_score: e.target.value })}
          >
            <option value="0">Any</option>
            <option value="50">50+</option>
            <option value="60">60+</option>
            <option value="70">70+</option>
          </select>
        </div>
        <div>
          <label htmlFor="opp-sector" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Sector</label>
          <input
            id="opp-sector"
            type="text"
            className="input-field w-48"
            placeholder="e.g. Technology"
            value={filters.sector}
            onChange={(e) => setFilters({ ...filters, sector: e.target.value })}
          />
        </div>
        <button type="submit" className="btn-sm btn-primary">Apply</button>
        {hasActiveFilters && (
          <button type="button" className="btn-sm btn-secondary" onClick={clearFilters}>Clear</button>
        )}
      </form>

      {error && (
        <div role="alert" className="mb-6 p-4 rounded-lg border border-error/30 bg-error/5 text-sm text-error">
          <p>Could not load opportunities: {error}</p>
          <button className="btn-secondary btn-sm mt-2" onClick={loadOpportunities}>Retry</button>
        </div>
      )}

      {loading && (
        <div className="card py-20 text-center text-on-surface-variant">
          <span className="material-symbols-outlined text-4xl mb-2 block animate-pulse">insights</span>
          <p className="text-sm">Loading market opportunities…</p>
        </div>
      )}

      {!loading && (
        <>
          <div className="card overflow-hidden !p-0 mb-6">
            <div className="p-widget-padding border-b border-outline-variant bg-surface-container-low flex justify-between items-center">
              <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2">
                <span className="material-symbols-outlined text-tertiary">insights</span>
                AI-Scored Opportunities
              </h3>
              <span className="text-xs data-font text-on-surface-variant">{opportunities.length} companies</span>
            </div>
            {opportunities.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-surface-container-highest border-b border-outline-variant">
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Ticker</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Screening Score</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Risk</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Volatility</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Sector</th>
                      <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold text-right">Signal</th>
                      <th className="py-2 px-4 w-10"></th>
                    </tr>
                  </thead>
                  <tbody className="text-sm data-font text-on-surface">
                    {opportunities.map((opp) => {
                      const signal = signalFor(opp.recommendation);
                      const expanded = expandedTicker === opp.ticker;
                      return (
                        <Fragment key={opp.ticker}>
                          <tr
                            onClick={() => toggleRow(opp.ticker)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault();
                                toggleRow(opp.ticker);
                              }
                            }}
                            tabIndex={0}
                            aria-expanded={expanded}
                            className={`${expanded ? 'bg-surface-variant' : ''} border-b border-outline-variant hover:bg-surface-variant transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-secondary focus-visible:outline-offset-2`}
                          >
                            <td className="py-2 px-4 font-bold">{opp.ticker}</td>
                            <td className="py-2 px-4">
                              <div className="flex items-center gap-2">
                                <ProgressBar value={opp.score || 0} max={100} color={colorFor(opp.score)} showLabel={false} />
                                <span className="text-on-surface-variant">{opp.score != null ? Number(opp.score).toFixed(1) : '—'}</span>
                              </div>
                            </td>
                            <td className="py-2 px-4">
                              <span className={opp.risk_score == null ? 'text-on-surface-variant' : opp.risk_score > 60 ? 'text-error' : opp.risk_score > 30 ? 'text-secondary' : 'text-tertiary'}>
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
                            <td className="py-2 px-4 text-on-surface-variant">
                              <button
                                className="p-1 rounded hover:bg-surface-container-highest focus-visible:outline-2 focus-visible:outline-secondary"
                                aria-label={expanded ? `Collapse score breakdown for ${opp.ticker}` : `Expand score breakdown for ${opp.ticker}`}
                                aria-expanded={expanded}
                                onClick={(e) => { e.stopPropagation(); toggleRow(opp.ticker); }}
                              >
                                <span className="material-symbols-outlined text-sm transition-transform" style={{ transform: expanded ? 'rotate(180deg)' : 'none' }}>expand_more</span>
                              </button>
                            </td>
                          </tr>
                          {expanded && (
                            <tr>
                              <td colSpan={7} className="p-0">
                                <ScoreComponents opp={opp} onNavigate={navigate} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : !error ? (
              <div className="py-14 text-center text-on-surface-variant">
                <span className="material-symbols-outlined text-4xl mb-2 block">search</span>
                <p>{hasActiveFilters ? 'No companies match your filters.' : 'No scored opportunities yet.'}</p>
                <p className="text-xs mt-1">
                  {hasActiveFilters
                    ? 'Try relaxing the minimum score or clearing the sector filter.'
                    : 'Run AI analysis on companies, then revisit here.'}
                </p>
                {!hasActiveFilters && (
                  <button className="btn-sm btn-primary mt-4" onClick={() => navigate('/analysis')}>Run AI Analysis</button>
                )}
              </div>
            ) : null}
          </div>

          {/* Quick Actions */}
          <div className="card">
            <h3 className="text-lg font-semibold text-on-surface mb-3">Research</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <Link to="/companies" className="p-3 bg-surface-variant border border-outline-variant rounded hover:bg-surface-bright hover:border-secondary transition-colors group block">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary">domain</span>
                  <span className="text-sm text-on-surface">Browse Companies</span>
                </div>
                <p className="text-xs text-on-surface-variant mt-1">Fundamentals, technicals, and financial metrics.</p>
              </Link>
              <Link to="/analysis" className="p-3 bg-surface-variant border border-outline-variant rounded hover:bg-surface-bright hover:border-secondary transition-colors group block">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-on-surface-variant group-hover:text-tertiary">memory</span>
                  <span className="text-sm text-on-surface">AI Analysis Jobs</span>
                </div>
                <p className="text-xs text-on-surface-variant mt-1">Run and monitor AI investment research pipelines.</p>
              </Link>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
