import { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getOpportunities } from '../services/api';
import { opportunityScore } from '../services/opportunityScore';
import StatusChip from '../components/StatusChip';
import Pagination from '../components/Pagination';
import { useAuth } from '../services/auth';
import { preferenceKey, readPreferences, togglePreference } from '../services/companyPreferences';
import { scoreHelp, opportunitySummary, financialLimitations } from '../services/researchSummary';

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

function formatDate(value) {
  if (!value) return null;
  const d = new Date(value);
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function ScoreComponents({ opp, onNavigate }) {
  const hasAnalysis = !!opp.analysis_id;
  const summary = opportunitySummary(opp);
  return (
    <div className="px-4 pb-4">
      <div className="p-4 bg-surface-container-low rounded border border-outline-variant">
        <p className="text-sm mb-2">{summary.reason}</p>
        <p className="text-sm mb-2">{summary.concern}</p>
        {financialLimitations(opp).map(message => <p key={message} className="text-xs text-secondary mb-2">{message}</p>)}
        <p className="text-xs text-on-surface-variant mb-3">{hasAnalysis ? 'A deep dive is available below. Review its coverage and evidence.' : 'Screening result only. Run a deep dive to inspect the explanation and missing data.'}</p>
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-on-surface-variant uppercase tracking-wider data-font">Score components</span>
          <span className="text-[10px] text-on-surface-variant data-font">
            {opp.score_source === 'analysis' ? 'Deep AI Analysis' : 'Screening model'}
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
  const { user } = useAuth();
  const userId = user?.id;
  const [savedPreferences, setSavedPreferences] = useState({ userId: null, values: {} });
  const preferences = savedPreferences.userId === userId ? savedPreferences.values : readPreferences({ getItem: key => window.localStorage.getItem(key) }, userId);
  const [personalView, setPersonalView] = useState('all');
  const [page, setPage] = useState(0);
  const [preferenceError, setPreferenceError] = useState(null);
  const [lastHidden, setLastHidden] = useState(null);
  function changePreference(ticker, field) {
    setPage(0);
    const key = preferenceKey(userId);
    if (!key) return;
    const values = togglePreference(preferences, ticker, field);
    try {
      window.localStorage.setItem(key, JSON.stringify(values));
      setSavedPreferences({ userId, values });
      if (field === 'hidden') setLastHidden(values[ticker].hidden ? { ticker, userId } : null);
      setPreferenceError(null);
    } catch { setPreferenceError('Could not save your preferences. Browser storage may be unavailable.'); }
  }
  const navigate = useNavigate();
  const requestSequence = useRef(0);
  const [opportunities, setOpportunities] = useState([]);
  const visibleOpportunities = opportunities.filter(opp => !preferences[opp.ticker]?.hidden &&
    (personalView !== 'watched' || preferences[opp.ticker]?.watched));
  const currentPage = Math.min(page, Math.max(0, Math.ceil(visibleOpportunities.length / 5) - 1));
  const pageOpportunities = visibleOpportunities.slice(currentPage * 5, currentPage * 5 + 5);
  const [loading, setLoading] = useState(true);
  const [expandedTicker, setExpandedTicker] = useState(null);
  const [error, setError] = useState(null);
  // `filters` holds the in-progress form values; `applied` holds what the list
  // is actually rendered with (applied via the Apply button).
  const [filters, setFilters] = useState({ min_score: '0', sector: '', ticker: '' });
  const [applied, setApplied] = useState({ min_score: '0', sector: '', ticker: '' });
  const hasActiveFilters = applied.min_score !== '0' || !!applied.sector.trim() || !!applied.ticker.trim();

  const loadOpportunities = useCallback(async (background = false) => {
    const sequence = ++requestSequence.current;
    if (!background) setLoading(true);
    setError(null);
    try {
      const params = { limit: 100 };
      if (applied.ticker.trim()) params.ticker = applied.ticker.trim().toUpperCase();
      if (Number(applied.min_score) > 0) params.min_score = Number(applied.min_score);
      if (applied.sector.trim()) params.sector = applied.sector.trim();
      const rows = [];
      for (let offset = 0; ; offset += params.limit) {
        const data = await getOpportunities({ ...params, offset });
        if (sequence !== requestSequence.current) return;
        const batch = data?.opportunities || [];
        rows.push(...batch);
        if (batch.length < params.limit) break;
      }
      setOpportunities([...new Map(rows.map(row => [row.ticker, row])).values()]);
    } catch (e) {
      if (sequence !== requestSequence.current) return;
      setError(e.message || 'Failed to load opportunities');
      if (!background) setOpportunities([]);
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [applied]);

  useEffect(() => {
    loadOpportunities();
    const refresh = () => { if (!document.hidden) loadOpportunities(true); };
    const timer = window.setInterval(refresh, 30000);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [loadOpportunities]);

  function applyFilters(event) {
    event.preventDefault();
    setPage(0);
    setApplied({ min_score: filters.min_score, sector: filters.sector, ticker: filters.ticker.trim().toUpperCase() });
  }

  function clearFilters() {
    setPage(0);
    setFilters({ min_score: '0', sector: '', ticker: '' });
    setApplied({ min_score: '0', sector: '', ticker: '' });
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
            Latest completed deep-dive scores, with screening scores for companies awaiting analysis.
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

      <details className="card mb-4">
        <summary className="cursor-pointer text-sm font-semibold flex items-center gap-2">
          <span aria-hidden="true" className="material-symbols-outlined text-secondary">info</span>
          How to read these scores
        </summary>
        <div className="grid md:grid-cols-2 gap-4 mt-4 text-sm">
          <p><strong>Investment score:</strong> {scoreHelp.investment}</p>
          <p><strong>Risk:</strong> {scoreHelp.risk}</p>
        </div>
        <p className="text-xs text-on-surface-variant mt-3">Expand a company to inspect the breakdown, coverage and next research step.</p>
      </details>
      {userId != null && <section className="card mb-4" aria-label="Personal company preferences">
        <div className="flex flex-wrap justify-between items-center gap-3">
          <div className="flex gap-1 rounded-lg bg-surface-container-highest p-1" role="group" aria-label="Company view">
            <button className={`px-4 py-2 rounded-md text-sm font-semibold transition-colors ${personalView === 'all' ? 'bg-secondary text-on-secondary' : 'text-on-surface-variant hover:bg-surface-variant'}`} aria-pressed={personalView === 'all'} onClick={() => { setPersonalView('all'); setPage(0); }}>All companies</button>
            <button className={`px-4 py-2 rounded-md text-sm font-semibold transition-colors inline-flex items-center gap-2 ${personalView === 'watched' ? 'bg-secondary text-on-secondary' : 'text-on-surface-variant hover:bg-surface-variant'}`} aria-pressed={personalView === 'watched'} onClick={() => { setPersonalView('watched'); setPage(0); }}><span aria-hidden="true" className="material-symbols-outlined text-base">bookmark</span>Watchlist</button>
          </div>
          <span className="text-xs text-on-surface-variant">{visibleOpportunities.length} of {opportunities.length} loaded companies</span>
        </div>
        <p className="text-xs text-on-surface-variant mt-3">Saved for your account in this browser. Five companies per page. Views include all results matching your filters.</p>
        {Object.values(preferences).some(p => p.hidden) && <details className="mt-3 border-t border-outline-variant pt-3">
          <summary className="cursor-pointer text-sm text-on-surface-variant">Hidden companies ({Object.values(preferences).filter(p => p.hidden).length}) · Manage</summary>
          <div className="flex flex-wrap gap-2 mt-3">{Object.entries(preferences).filter(([, p]) => p.hidden).map(([ticker]) => <button key={ticker} className="btn-sm btn-secondary inline-flex items-center gap-2" onClick={() => changePreference(ticker, 'hidden')}><span aria-hidden="true" className="material-symbols-outlined text-base">visibility</span>Restore {ticker}</button>)}</div>
        </details>}
        {lastHidden?.userId === userId && <div role="status" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface-container-highest px-3 py-2 text-sm"><span>{lastHidden.ticker} hidden from your view</span><button className="btn-sm btn-secondary" onClick={() => changePreference(lastHidden.ticker, 'hidden')}>Undo</button></div>}
        {preferenceError && <p role="alert" className="text-error mt-2">{preferenceError}</p>}
      </section>}
      {/* Filters apply before API pagination. */}
      <form onSubmit={applyFilters} aria-label="Opportunity filters" className="card mb-6 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="opp-ticker" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Search ticker</label>
          <input id="opp-ticker" type="search" className="input-field w-48 uppercase" placeholder="e.g. AAPL" maxLength={32} autoComplete="off" spellCheck={false} value={filters.ticker} onChange={e => setFilters({ ...filters, ticker: e.target.value })} />
        </div>
        <div>
          <label htmlFor="opp-min-score" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Minimum investment score</label>
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
                {personalView === 'watched' ? 'Your Watchlist' : 'AI-Scored Opportunities'}
              </h3>
              <span className="text-xs data-font text-on-surface-variant">{visibleOpportunities.length} {visibleOpportunities.length === 1 ? 'company' : 'companies'}</span>
            </div>
            {opportunities.length > 0 ? (
              <div>
                <div className="divide-y divide-outline-variant">
                  {pageOpportunities.map(opp => {
                    const score = opportunityScore(opp);
                    const signal = signalFor(opp.recommendation);
                    const expanded = expandedTicker === opp.ticker;
                    const limitations = financialLimitations(opp);
                    return <article key={opp.ticker} className={`transition-colors ${expanded ? 'bg-surface-container-low' : 'hover:bg-surface-container-low'}`} aria-label={`${opp.ticker} research opportunity`}>
                      <div className="p-5 md:p-6">
                        <div className="flex flex-wrap justify-between items-start gap-3 mb-4">
                          <div>
                            <Link className="text-xl font-bold tracking-tight hover:text-secondary" to={`/companies/${opp.ticker}`}>{opp.ticker}</Link>
                            <p className="text-xs text-on-surface-variant mt-1">{opp.sector || 'Sector unavailable'}</p>
                          </div>
                          <StatusChip status={signal.status} label={signal.label} />
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                          <div className="border-l-2 border-secondary pl-3">
                            <p className="text-xs text-on-surface-variant">Investment score</p>
                            <p className="text-2xl font-semibold data-font mt-1">{score != null ? Number(score).toFixed(1) : '—'}<span className="text-xs text-on-surface-variant ml-1">/ 100</span></p>
                            <p className="text-xs text-on-surface-variant">Higher is more attractive</p>
                          </div>
                          <div className="pl-3 border-l-2 border-outline-variant">
                            <p className="text-xs text-on-surface-variant">Risk score</p>
                            <p className={`text-2xl font-semibold data-font mt-1 ${opp.risk_score > 60 ? 'text-error' : 'text-on-surface'}`}>{opp.risk_score != null ? Number(opp.risk_score).toFixed(0) : '—'}<span className="text-xs text-on-surface-variant ml-1">/ 100</span></p>
                            <p className="text-xs text-on-surface-variant">Higher means more concern</p>
                          </div>
                          <div><p className="text-xs text-on-surface-variant">Research source</p><p className="text-sm font-semibold mt-2">{opp.score_source === 'analysis' ? 'Completed deep dive' : 'Screening model'}</p><p className="text-xs text-on-surface-variant mt-1">{formatDate(opp.score_timestamp) || 'Date unavailable'}</p></div>
                          <div><p className="text-xs text-on-surface-variant">Price volatility</p><p className="text-sm font-semibold mt-2">{opp.volatility != null ? `${(Number(opp.volatility) * 100).toFixed(1)}%` : 'Unavailable'}</p><p className="text-xs text-on-surface-variant mt-1">Variation in historical returns</p></div>
                        </div>
                        {limitations.length > 0 && <div className="flex items-start gap-2 text-xs text-secondary bg-surface-container-highest rounded-lg px-3 py-2 mb-4"><span aria-hidden="true" className="material-symbols-outlined text-base shrink-0">info</span><p>{limitations[0]}</p></div>}
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div className="flex flex-wrap gap-2">
                            {userId != null && <>
                              <button className={`btn-sm inline-flex items-center gap-1.5 ${preferences[opp.ticker]?.watched ? 'btn-primary' : 'btn-secondary'}`} aria-label={`${preferences[opp.ticker]?.watched ? 'Unwatch' : 'Watch'} ${opp.ticker}`} aria-pressed={!!preferences[opp.ticker]?.watched} onClick={() => changePreference(opp.ticker, 'watched')}><span aria-hidden="true" className="material-symbols-outlined text-base">{preferences[opp.ticker]?.watched ? 'bookmark_added' : 'bookmark_add'}</span>{preferences[opp.ticker]?.watched ? 'Watching' : 'Watch'}</button>
                              <button className="btn-sm btn-secondary inline-flex items-center gap-1.5" aria-label={`Hide ${opp.ticker}`} onClick={() => changePreference(opp.ticker, 'hidden')}><span aria-hidden="true" className="material-symbols-outlined text-base">visibility_off</span>Hide</button>
                            </>}
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <button className="btn-sm btn-secondary inline-flex items-center gap-1" aria-expanded={expanded} aria-controls={`research-${opp.ticker}`} onClick={() => toggleRow(opp.ticker)}>Score details<span aria-hidden="true" className="material-symbols-outlined text-base">{expanded ? 'expand_less' : 'expand_more'}</span></button>
                            <Link className="btn-sm btn-primary inline-flex items-center gap-1.5" to={opp.analysis_id ? `/analysis/${opp.analysis_id}` : `/analysis?ticker=${encodeURIComponent(opp.ticker)}`}><span aria-hidden="true" className="material-symbols-outlined text-base">{opp.analysis_id ? 'description' : 'bolt'}</span>{opp.analysis_id ? 'Read deep dive' : 'Analyze company'}</Link>
                          </div>
                        </div>
                      </div>
                      <div id={`research-${opp.ticker}`} hidden={!expanded}>{expanded && <ScoreComponents opp={opp} onNavigate={navigate} />}</div>
                    </article>;
                  })}
                </div>
                <Pagination label="Company pages" page={currentPage} hasMore={(currentPage + 1) * 5 < visibleOpportunities.length} loading={loading} onPrev={() => setPage(currentPage - 1)} onNext={() => setPage(currentPage + 1)} />
                {!visibleOpportunities.length && <div role="status" className="p-8 text-center"><span aria-hidden="true" className="material-symbols-outlined text-4xl text-on-surface-variant mb-3">bookmark_border</span><p className="font-semibold">{personalView === 'watched' ? 'Your watchlist is empty for these filters' : 'No visible companies'}</p><p className="text-sm text-on-surface-variant mt-2">{personalView === 'watched' ? 'Browse all companies and select Watch to save one, or adjust your filters.' : 'Restore a hidden company or adjust your filters.'}</p><button className="btn-sm btn-secondary mt-4" onClick={() => { setPersonalView('all'); setPage(0); }}>Browse all companies</button></div>}
              </div>
            ) : !error ? (
              <div className="py-14 text-center text-on-surface-variant">
                <span className="material-symbols-outlined text-4xl mb-2 block">search</span>
                <p>{hasActiveFilters ? 'No companies match your filters.' : 'No scored opportunities yet.'}</p>
                <p className="text-xs mt-1">
                  {hasActiveFilters
                    ? 'Try another ticker or clear your filters.'
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
                  <span className="text-sm text-on-surface">AI Analysis</span>
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
