import { useState, useEffect, useCallback, useRef } from 'react';
import {
  getBacktestRuns,
  getBacktestRun,
  getBacktestTrades,
  createBacktestRun,
  getBacktestSnapshots,
} from '../services/api';
import { useToast } from '../components/Toast';
import MetricTile from '../components/MetricTile';
import StatusChip from '../components/StatusChip';
import EquityChart from '../components/EquityChart';
import Pagination from '../components/Pagination';

const EMPTY_FORM = {
  name: '',
  strategy: 'equal_weight',
  start_date: '',
  end_date: '',
  initial_capital: 100000,
  benchmark_ticker: 'SPY',
  tickers: '',
  snapshot_id: '',
};

export default function Backtest() {
  const toast = useToast();
  const detailVersion = useRef(0);
  const [hasMoreTrades, setHasMoreTrades] = useState(false);
  const [loadingTrades, setLoadingTrades] = useState(false);
  const [runs, setRuns] = useState([]);
  const [runPage, setRunPage] = useState(0);
  const [snapshotPage, setSnapshotPage] = useState(0);
  const [moreRuns, setMoreRuns] = useState(false);
  const [moreSnapshots, setMoreSnapshots] = useState(false);
  // One version counter + one loading flag per table. They were previously a
  // single shared pair, which meant paging the *snapshots* table set the runs
  // loading flag too — so the runs table re-rendered as its skeleton (and
  // refetched) on every snapshot page change, and vice versa.
  const runsVersion = useRef(0);
  const snapshotsVersion = useRef(0);
  const [snapshots, setSnapshots] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [trades, setTrades] = useState([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [snapshotsLoading, setSnapshotsLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [createResult, setCreateResult] = useState(null);

  const loadRuns = useCallback(async () => {
    const version = ++runsVersion.current;
    setRunsLoading(true);
    try {
      const data = await getBacktestRuns({ limit: 21, offset: runPage * 20 });
      if (version !== runsVersion.current) return;
      setRuns((data?.runs || []).slice(0, 20));
      setMoreRuns((data?.runs || []).length > 20);
    } catch {
      if (version !== runsVersion.current) return;
      setRuns([]);
      setMoreRuns(false);
      toast('Failed to load backtest runs.', 'error');
    } finally {
      if (version === runsVersion.current) setRunsLoading(false);
    }
  }, [toast, runPage]);

  const loadSnapshots = useCallback(async () => {
    const version = ++snapshotsVersion.current;
    setSnapshotsLoading(true);
    try {
      const data = await getBacktestSnapshots({ limit: 11, offset: snapshotPage * 10 });
      if (version !== snapshotsVersion.current) return;
      setSnapshots((data?.snapshots || []).slice(0, 10));
      setMoreSnapshots((data?.snapshots || []).length > 10);
    } catch {
      if (version !== snapshotsVersion.current) return;
      setSnapshots([]);
      setMoreSnapshots(false);
      toast('Failed to load snapshots.', 'error');
    } finally {
      if (version === snapshotsVersion.current) setSnapshotsLoading(false);
    }
  }, [toast, snapshotPage]);

  const invalidateRequests = useCallback(() => {
    runsVersion.current++;
    snapshotsVersion.current++;
    detailVersion.current++;
  }, []);
  // Independent effects: each table reloads only for its own page changes.
  useEffect(() => { loadRuns(); }, [loadRuns]);
  useEffect(() => { loadSnapshots(); }, [loadSnapshots]);
  useEffect(() => invalidateRequests, [invalidateRequests]);

  async function handleViewRun(runId) {
    const version = ++detailVersion.current;
    setLoadingTrades(false);
    try {
      // The detail endpoint already embeds trades — no second fetch needed.
      const detail = await getBacktestRun(runId);
      if (version !== detailVersion.current) return;
      setHasMoreTrades(Boolean(detail.has_more));
      setSelectedRun(detail);
      setTrades(detail?.trades || []);
    } catch (err) {
      toast(err.message || 'Failed to load run details.', 'error');
    }
  }

  async function loadMoreTrades() {
    if (loadingTrades) return;
    const version = detailVersion.current;
    setLoadingTrades(true);
    try {
      const data = await getBacktestTrades(selectedRun.run.id, { limit: 100, offset: trades.length });
      if (version !== detailVersion.current) return;
      setTrades(previous => [...previous, ...data.trades]);
      setHasMoreTrades(data.has_more);
    } catch (error) {
      if (version === detailVersion.current) toast(error.message, 'error');
    } finally {
      if (version === detailVersion.current) setLoadingTrades(false);
    }
  }

  async function handleCreate(e) {
    e.preventDefault();
    setCreateResult(null);
    if (form.start_date && form.end_date && new Date(form.end_date) <= new Date(form.start_date)) {
      setCreateResult({ success: false, message: 'End date must be after start date.' });
      return;
    }
    setSubmitting(true);
    try {
      const data = await createBacktestRun({
        ...form,
        tickers: form.tickers.trim() ? form.tickers.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean) : null,
        initial_capital: Number(form.initial_capital),
        snapshot_id: form.snapshot_id === '' ? null : Number(form.snapshot_id),
      });
      setCreateResult({ success: true, data });
      setShowCreate(false);
      setForm(EMPTY_FORM);
      // Refresh runs
      setRunPage(0);
      if (runPage === 0) await loadRuns();
    } catch (err) {
      setCreateResult({ success: false, message: err.message });
      toast(err.message || 'Failed to create backtest run.', 'error');
    } finally {
      setSubmitting(false);
    }
  }

  const result = selectedRun?.result;
  const benchmark = selectedRun?.benchmark;
  // Snapshot pinning disclosure (audit F12) — see compute_snapshot_coverage.
  const coverage = selectedRun?.run?.snapshot_coverage;

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Backtesting</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Strategy evaluation, performance metrics, and trade analysis.
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary flex items-center gap-2" onClick={() => { detailVersion.current++; setLoadingTrades(false); setSelectedRun(null); setTrades([]); loadRuns(); loadSnapshots(); }}>
            <span className="material-symbols-outlined text-sm">refresh</span> Refresh
          </button>
          <button className="btn-primary flex items-center gap-2" onClick={() => { setShowCreate(!showCreate); if (!showCreate) loadRuns(); }}>
            <span className="material-symbols-outlined text-sm">add</span>
            New Backtest
          </button>
        </div>
      </div>

      {/* Create Form */}
      {showCreate && (
        <div className="card mb-6">
          <h3 className="text-lg font-semibold text-on-surface mb-4">Create Backtest Run</h3>
          <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label htmlFor="backtest-name" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Name</label>
              <input id="backtest-name" name="backtest-name" className="input-field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="My Backtest" required />
            </div>
            <div>
              <label htmlFor="backtest-strategy" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Strategy</label>
              <select id="backtest-strategy" name="backtest-strategy" className="select-field" value={form.strategy} onChange={(e) => setForm({ ...form, strategy: e.target.value })}>
                <option value="equal_weight">Equal Weight</option>
                <option value="momentum">Momentum</option>
                <option value="score_threshold">Score Threshold</option>
                <option value="portfolio_optimizer">Portfolio Optimizer</option>
              </select>
            </div>
            <div>
              <label htmlFor="backtest-benchmark" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Benchmark</label>
              <input id="backtest-benchmark" name="backtest-benchmark" className="input-field uppercase data-font" value={form.benchmark_ticker} onChange={(e) => setForm({ ...form, benchmark_ticker: e.target.value })} />
            </div>
            <div>
              <label htmlFor="backtest-start-date" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Start Date</label>
              <input id="backtest-start-date" name="backtest-start-date" className="input-field data-font" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} required />
            </div>
            <div>
              <label htmlFor="backtest-end-date" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">End Date</label>
              <input id="backtest-end-date" name="backtest-end-date" className="input-field data-font" type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} required />
            </div>
            <div>
              <label htmlFor="backtest-initial-capital" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Initial Capital</label>
              <input id="backtest-initial-capital" name="backtest-initial-capital" className="input-field data-font" type="number" min="1" step="any" value={form.initial_capital} onChange={(e) => setForm({ ...form, initial_capital: e.target.value })} required />
            </div>
            <div className="md:col-span-3">
              <label htmlFor="backtest-tickers-comma-separated" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Tickers (comma-separated)</label>
              <input id="backtest-tickers-comma-separated" name="backtest-tickers-comma-separated" className="input-field uppercase data-font" value={form.tickers} onChange={(e) => setForm({ ...form, tickers: e.target.value })} placeholder="Leave blank for all tracked companies" />
            </div>
            <div className="md:col-span-3">
              <label htmlFor="backtest-point-in-time-snapshot-optional" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Point-in-Time Snapshot (optional)</label>
              <select id="backtest-point-in-time-snapshot-optional" name="backtest-point-in-time-snapshot-optional" className="select-field" value={form.snapshot_id} onChange={(e) => setForm({ ...form, snapshot_id: e.target.value })}>
                <option value="">None — use live data</option>
                {snapshots.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} (as of {s.as_of ? new Date(s.as_of).toLocaleDateString() : '—'})
                  </option>
                ))}
              </select>
            </div>
            <div className="md:col-span-3 flex gap-2">
              <button type="submit" className="btn-primary" disabled={submitting}>
                {submitting ? 'Running...' : 'Run Backtest'}
              </button>
              <button type="button" className="btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
            </div>
          </form>
          {createResult && (
            <div className={`mt-4 p-3 rounded border text-sm ${createResult.success ? 'bg-tertiary-fixed/10 border-tertiary-fixed/30 text-tertiary' : 'bg-error-container/20 border-error-container/50 text-error'}`}>
              {createResult.success ? `Backtest created: ${createResult.data.name || createResult.data.id}` : createResult.message}
            </div>
          )}
        </div>
      )}

      {/* Run Detail */}
      {selectedRun && (
        <div className="mb-6">
          <button onClick={() => { detailVersion.current++; setLoadingTrades(false); setSelectedRun(null); setTrades([]); }} className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm">
            <span className="material-symbols-outlined text-sm">arrow_back</span>
            Back to Runs
          </button>

          {/* Failure reason */}
          {selectedRun.run?.status === 'failed' && selectedRun.run?.error_message && (
            <div className="mb-6 p-3 rounded border bg-error-container/20 border-error-container/50 text-error text-sm">
              <span className="font-semibold">Run failed:</span> {selectedRun.run.error_message}
            </div>
          )}

          {/* Snapshot pinning disclosure (audit F12): never overstate
              reproducibility — score-driven strategies read live score history
              even on a pinned run, and the benchmark may fall back to live. */}
          {coverage?.mode === 'pinned' && (
            <div className="mb-6 p-3 rounded border border-tertiary/40 bg-tertiary/10 text-sm text-on-surface">
              <span className="font-semibold">Fully pinned:</span> all decision inputs
              (prices{coverage.pinned?.includes('benchmark') ? ' and benchmark' : ''})
              served from snapshot #{coverage.snapshot_id}
              {coverage.snapshot_as_of ? ` (as of ${new Date(coverage.snapshot_as_of).toLocaleDateString()})` : ''}.
            </div>
          )}
          {coverage?.mode === 'partially_pinned' && (
            <div className="mb-6 p-3 rounded border border-secondary-container/50 bg-secondary-container/10 text-sm text-on-surface">
              <span className="font-semibold">Partially pinned:</span> prices
              {coverage.pinned?.includes('benchmark') ? ' and benchmark' : ''} served from
              snapshot #{coverage.snapshot_id}
              {coverage.snapshot_as_of ? ` (as of ${new Date(coverage.snapshot_as_of).toLocaleDateString()})` : ''};
              {' '}{(coverage.live || []).join(', ').replace(/_/g, ' ')} read from live tables —
              re-runs can differ if that live data changes.
            </div>
          )}
          {coverage?.mode === 'unpinned' && (
            <p className="mb-6 text-xs text-on-surface-variant">
              Data pinning: none — inputs read from live tables ({(coverage.live || []).join(', ').replace(/_/g, ' ')}).
            </p>
          )}

          {/* Performance Metrics */}
          {result && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-gutter mb-2">
                <MetricTile label="Total Return" value={result.total_return != null ? `${(result.total_return * 100).toFixed(2)}%` : '—'} icon="trending_up" color={result.total_return >= 0 ? 'tertiary' : 'error'} />
                <MetricTile label="Sharpe Ratio" value={result.sharpe_ratio?.toFixed(2) || '—'} icon="query_stats" color="secondary" />
                <MetricTile label="Max Drawdown" value={result.max_drawdown != null ? `${(result.max_drawdown * 100).toFixed(1)}%` : '—'} icon="trending_down" color="error" />
                <MetricTile label="Win Rate*" value={result.win_rate != null ? `${(result.win_rate * 100).toFixed(1)}%` : '—'} icon="military_tech" color="tertiary" />
              </div>
              {/* Audit F13: this is a sell-execution proxy (share of sells priced
                  above average cost), not closed-trade realized P&L — a single
                  sell can read 100% wins next to a negative total return.
                  Assumes 0% risk-free, no fees/slippage unless documented. */}
              <p className="text-[11px] text-on-surface-variant mb-6">
                *Win rate = share of SELL executions priced above that position's average cost, weighted by outcome count (not by shares or profit). Breakeven is not counted as a win. Always read it alongside total return.
              </p>
            </>
          )}

          {/* Equity Curve Chart */}
          {result?.equity_curve?.points?.length > 1 && (
            <div className="card mb-6">
              <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2 mb-2">
                <span className="material-symbols-outlined text-tertiary">show_chart</span>
                Portfolio Value
                {selectedRun.run?.initial_capital != null && (
                  <span className="text-xs text-on-surface-variant font-normal ml-2 data-font">
                    started at ${Number(selectedRun.run.initial_capital).toLocaleString()}
                  </span>
                )}
              </h3>
              <EquityChart
                points={result.equity_curve.points}
                initialCapital={selectedRun.run?.initial_capital ?? null}
              />
            </div>
          )}

          {/* Benchmark Comparison */}
          {benchmark && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-gutter mb-6">
              <div className="card">
                <p className="text-xs text-on-surface-variant mb-1">Strategy Return</p>
                <p className={`text-lg font-bold data-font ${(result?.total_return || 0) >= (benchmark.benchmark_return || 0) ? 'text-tertiary' : 'text-error'}`}>
                  {result?.total_return != null ? `${(result.total_return * 100).toFixed(2)}%` : '—'}
                </p>
              </div>
              <div className="card">
                <p className="text-xs text-on-surface-variant mb-1">Benchmark Return</p>
                <p className="text-lg font-bold data-font text-on-surface">
                  {benchmark.benchmark_return != null ? `${(benchmark.benchmark_return * 100).toFixed(2)}%` : '—'}
                </p>
              </div>
              <div className="card">
                <p className="text-xs text-on-surface-variant mb-1">Alpha</p>
                <p className={`text-lg font-bold data-font ${(benchmark.alpha || 0) >= 0 ? 'text-tertiary' : 'text-error'}`}>
                  {benchmark.alpha != null ? `${(benchmark.alpha * 100).toFixed(2)}%` : '—'}
                </p>
              </div>
              <div className="card">
                <p className="text-xs text-on-surface-variant mb-1">Beta</p>
                <p className="text-lg font-bold data-font text-on-surface">
                  {benchmark.beta?.toFixed(2) || '—'}
                </p>
              </div>
            </div>
          )}

          {/* Trades Table */}
          <div className="card overflow-hidden !p-0">
            <div className="p-widget-padding border-b border-outline-variant bg-surface-container-low">
              <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary">swap_horiz</span>
                Trades
                <span className="text-xs text-on-surface-variant font-normal ml-2 data-font">
                </span>
              </h3>
            </div>
            {hasMoreTrades && <div className="px-4 sm:px-6 py-3 border-b border-outline-variant bg-surface-container-lowest flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <p className="text-sm text-on-surface-variant">Showing {trades.length} trades; more are available.</p>
              <button className="btn-secondary btn-sm" disabled={loadingTrades} onClick={loadMoreTrades}>{loadingTrades ? 'Loading…' : 'Load more trades'}</button>
            </div>}
            {trades.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-sm data-font">
                  <thead>
                    <tr className="bg-surface-container-highest border-b border-outline-variant">
                      <th className="py-2 px-3 text-xs text-on-surface-variant">Date</th>
                      <th className="py-2 px-3 text-xs text-on-surface-variant">Ticker</th>
                      <th className="py-2 px-3 text-xs text-on-surface-variant">Action</th>
                      <th className="py-2 px-3 text-xs text-on-surface-variant text-right">Quantity</th>
                      <th className="py-2 px-3 text-xs text-on-surface-variant text-right">Price</th>
                      <th className="py-2 px-3 text-xs text-on-surface-variant text-right">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <tr key={t.id || i} className={`${i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'} border-b border-outline-variant`}>
                        <td className="py-1.5 px-3 text-on-surface-variant">{t.trade_date ? new Date(t.trade_date).toLocaleDateString() : '—'}</td>
                        <td className="py-1.5 px-3 font-bold">{t.ticker || '—'}</td>
                        <td className="py-1.5 px-3">
                          <StatusChip status={t.action === 'BUY' ? 'bullish' : 'bearish'} label={t.action?.toUpperCase()} />
                        </td>
                        <td className="py-1.5 px-3 text-right">{t.shares?.toFixed(2) || '—'}</td>
                        <td className="py-1.5 px-3 text-right">${t.price?.toFixed(2) || '—'}</td>
                        <td className="py-1.5 px-3 text-right">${t.amount?.toFixed(2) || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-on-surface-variant">
                <span className="material-symbols-outlined text-4xl mb-2 block">swap_horiz</span>
                <p>No trades recorded for this run.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Runs List */}
      {!selectedRun && (
        <div className="card overflow-hidden !p-0">
          <div className="p-widget-padding border-b border-outline-variant bg-surface-container-low">
            <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">history</span>
              Backtest Runs
            </h3>
          </div>
          {runsLoading ? (
            <div className="py-12 text-center text-on-surface-variant">
              <span className="material-symbols-outlined text-4xl mb-2 block animate-pulse">history</span>
              <p>Loading backtest runs…</p>
            </div>
          ) : runs.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm data-font">
                <thead>
                  <tr className="bg-surface-container-highest border-b border-outline-variant">
                    <th className="py-2 px-3 text-xs text-on-surface-variant">Name</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant">Strategy</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant">Status</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant">Period</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant text-right">Capital</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r, i) => (
                    <tr key={r.id} className={`${i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'} border-b border-outline-variant hover:bg-surface-variant transition-colors cursor-pointer`} onClick={() => handleViewRun(r.id)}>
                      <td className="py-2 px-3 font-semibold">{r.name || `Run #${r.id}`}</td>
                      <td className="py-2 px-3 text-on-surface-variant">{r.strategy || '—'}</td>
                      <td className="py-2 px-3" title={r.error_message || undefined}>
                        <StatusChip status={r.status || 'queued'} />
                      </td>
                      <td className="py-2 px-3 text-on-surface-variant">
                        {r.start_date ? new Date(r.start_date).toLocaleDateString() : '—'} → {r.end_date ? new Date(r.end_date).toLocaleDateString() : '—'}
                      </td>
                      <td className="py-2 px-3 text-right">${r.initial_capital?.toLocaleString() || '—'}</td>
                      <td className="py-2 px-3 text-right">
                        <button className="text-secondary hover:underline text-xs">View Details</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-12 text-center text-on-surface-variant">
              <span className="material-symbols-outlined text-4xl mb-2 block">history</span>
              <p>No backtest runs yet. Click "New Backtest" to create one.</p>
            </div>
          )}
          <Pagination
            label="Backtest run pages"
            page={runPage}
            hasMore={moreRuns}
            loading={runsLoading}
            onPrev={() => setRunPage((p) => p - 1)}
            onNext={() => setRunPage((p) => p + 1)}
          />
        </div>
      )}

      {/* Snapshots */}
      {!selectedRun && snapshots.length > 0 && (
        <div className="card overflow-hidden !p-0 mt-6">
          <div className="p-widget-padding border-b border-outline-variant bg-surface-container-low">
            <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2">
              <span className="material-symbols-outlined text-tertiary">camera</span>
              Point-in-Time Snapshots
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm data-font">
              <thead>
                <tr className="bg-surface-container-highest border-b border-outline-variant">
                    <th className="py-2 px-3 text-xs text-on-surface-variant">Name</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant">As Of</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant">Description</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map((s, i) => (
                  <tr key={s.id} className={`${i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'} border-b border-outline-variant`}>
                    <td className="py-2 px-3 font-semibold">{s.name}</td>
                    <td className="py-2 px-3 text-on-surface-variant">{s.as_of ? new Date(s.as_of).toLocaleDateString() : '—'}</td>
                    <td className="py-2 px-3 text-on-surface-variant">{s.description || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            label="Snapshot pages"
            page={snapshotPage}
            hasMore={moreSnapshots}
            loading={snapshotsLoading}
            onPrev={() => setSnapshotPage((p) => p - 1)}
            onNext={() => setSnapshotPage((p) => p + 1)}
          />
        </div>
      )}
    </div>
  );
}