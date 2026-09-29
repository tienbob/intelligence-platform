import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { createCompanyAnalysis, getAnalysisJobs, deleteAnalysis, cancelAnalysis } from '../services/api';
import { useToast } from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';
import StatusChip from '../components/StatusChip';
import MetricTile from '../components/MetricTile';
import { REFRESH_ANALYSIS_JOBS_MS } from '../config';

const PAGE_SIZE = 20;
const ACTIVE = ['queued', 'collecting_data', 'calculating_metrics', 'retrieving_context', 'llm_analysis', 'risk_analysis', 'running', 'processing'];
const SOURCES = ['news', 'fundamentals', 'technical', 'macro'];

export default function Analysis() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number.parseInt(params.get('page'), 10) || 1);
  const [version, setVersion] = useState(0);
  const [state, setState] = useState(null);
  const [ticker, setTicker] = useState('');
  const [sources, setSources] = useState(Object.fromEntries(SOURCES.map(key => [key, true])));
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const [created, setCreated] = useState(null);
  const [pending, setPending] = useState({});
  const [confirmDelete, setConfirmDelete] = useState(null);
  const current = state?.page === page ? state : null;
  const data = current?.data;
  const jobs = data?.jobs || [];
  const total = data?.total || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const counts = data?.status_counts || {};
  const supportsInclusions = data?.supports_inclusions !== false;

  useEffect(() => {
    let stopped = false;
    let timer;
    async function load() {
      try {
        const data = await getAnalysisJobs({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
        if (!stopped) setState({ page, data, error: null });
      } catch (error) {
        if (!stopped) setState(previous => ({ page, data: previous?.page === page ? previous.data : null, error: error.message }));
      }
      if (!stopped && REFRESH_ANALYSIS_JOBS_MS > 0) timer = setTimeout(load, REFRESH_ANALYSIS_JOBS_MS);
    }
    load();
    return () => { stopped = true; clearTimeout(timer); };
  }, [page, version]);

  async function act(job, action) {
    if (pending[job.analysis_id]) return;
    // Destructive deletes go through the styled ConfirmDialog (L3) instead of
    // the native window.confirm.
    if (action === 'delete') {
      setConfirmDelete(job);
      return;
    }
    setPending(previous => ({ ...previous, [job.analysis_id]: true }));
    try {
      const result = await cancelAnalysis(job.analysis_id);
      toast(`Analysis ${result.status}`, 'success');
      setVersion(value => value + 1);
    } catch (error) {
      toast(error.message || 'Action failed. Try again.', 'error');
    } finally {
      setPending(previous => ({ ...previous, [job.analysis_id]: false }));
    }
  }

  async function confirmDeleteAnalysis() {
    const job = confirmDelete;
    if (!job || pending[job.analysis_id]) return;
    setPending(previous => ({ ...previous, [job.analysis_id]: true }));
    try {
      await deleteAnalysis(job.analysis_id);
      toast('Analysis deleted', 'success');
      setConfirmDelete(null);
      if (jobs.length === 1 && page > 1) setParams({ page: String(page - 1) });
      setVersion(value => value + 1);
    } catch (error) {
      toast(error.message || 'Action failed. Try again.', 'error');
    } finally {
      setPending(previous => ({ ...previous, [job.analysis_id]: false }));
    }
  }

  async function create(event) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setFormError('');
    try {
      const result = await createCompanyAnalysis({
        ticker: ticker.trim().toUpperCase(),
        ...Object.fromEntries(SOURCES.map(key => [`include_${key}`, supportsInclusions ? sources[key] : true])),
      });
      setCreated(result);
      setTicker('');
      setParams({ page: '1' });
      setVersion(value => value + 1);
      toast('Analysis queued', 'success');
    } catch (error) {
      setFormError(error.message || 'Could not create analysis. Try again.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4 mb-6">
        <div>
          <h1 className="text-4xl font-bold text-on-surface flex items-center gap-3">
            <span aria-hidden="true" className="material-symbols-outlined text-secondary text-3xl">memory</span>
            AI Analysis
          </h1>
          <p className="text-sm text-on-surface-variant mt-2">Company research, investment signals, and the evidence behind them.</p>
        </div>
        <button className="btn-secondary btn-sm inline-flex items-center justify-center gap-2 self-start sm:self-auto" onClick={() => setVersion(value => value + 1)}>
          <span aria-hidden="true" className="material-symbols-outlined text-base">refresh</span> Refresh
        </button>
      </div>
      {created && <div role="status" className="flex flex-wrap items-center justify-between gap-3 p-4 mb-6 rounded-lg border border-tertiary/30 bg-tertiary/5 text-sm">
        <span className="flex items-center gap-2"><span aria-hidden="true" className="material-symbols-outlined text-tertiary text-lg">check_circle</span> Your analysis is queued.</span>
        <Link className="text-secondary hover:underline inline-flex items-center gap-1" to={`/analysis/${created.analysis_id}`}>View analysis <span aria-hidden="true" className="material-symbols-outlined text-base">arrow_forward</span></Link>
      </div>}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-gutter mb-6">
        {[
          ['Total Analyses', total, 'analytics', 'on-surface-variant'],
          ['In Progress', ACTIVE.reduce((sum, key) => sum + (counts[key] || 0), 0), 'autorenew', 'secondary'],
          ['Completed', counts.completed || 0, 'task_alt', 'tertiary'],
          ['Failed', counts.failed || 0, 'error_outline', 'error'],
        ].map(([label, value, icon, color]) => <MetricTile key={label} label={label} value={data ? value : '—'} icon={icon} color={color} />)}
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-gutter items-start">
        <section className="card xl:col-span-4 xl:order-2 !p-0 overflow-hidden">
          <div className="p-5 border-b border-outline-variant/60 bg-surface-container">
            <div className="flex items-center gap-2 mb-2"><span aria-hidden="true" className="material-symbols-outlined text-secondary text-xl">add_chart</span><h2 className="text-lg font-semibold">New Analysis</h2></div>
            <p className="text-xs leading-relaxed text-on-surface-variant">Choose a company and the data to include in your research.</p>
          </div>
          <form onSubmit={create} className="p-5 space-y-5">
            <div>
              <label htmlFor="analysis-ticker" className="block text-xs uppercase tracking-wider data-font text-on-surface-variant mb-2">Company ticker</label>
              <input id="analysis-ticker" name="ticker" className="input-field uppercase data-font !py-3" placeholder="e.g. AAPL" value={ticker} onChange={event => setTicker(event.target.value)} required pattern=".*\S.*" autoComplete="off" spellCheck={false} disabled={submitting} />
            </div>
            <fieldset disabled={submitting || !data || !supportsInclusions} className="grid grid-cols-2 gap-2 disabled:opacity-60">
              <legend className="text-xs uppercase tracking-wider data-font text-on-surface-variant mb-3">Research sources</legend>
              {SOURCES.map(key => <label key={key} className="flex items-center gap-2.5 capitalize text-sm p-3 bg-surface-container border border-outline-variant/50 rounded hover:border-secondary/60 transition-colors cursor-pointer has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-secondary"><input name={`include_${key}`} type="checkbox" className="accent-secondary-container w-3.5 h-3.5" checked={supportsInclusions ? sources[key] : true} onChange={event => setSources(previous => ({ ...previous, [key]: event.target.checked }))} />{key}</label>)}
            </fieldset>
            {!supportsInclusions && <p className="text-sm text-on-surface-variant">This analysis mode uses all data sources.</p>}
            {formError && <p role="alert" className="text-error">{formError}</p>}
            <button className="btn-primary w-full text-sm inline-flex items-center justify-center gap-2 !py-3" disabled={submitting || !data} type="submit"><span aria-hidden="true" className="material-symbols-outlined text-lg">{submitting ? 'hourglass_top' : 'play_arrow'}</span>{submitting ? 'Creating analysis…' : 'Run Analysis'}</button>
          </form>
          <div className="px-5 py-4 border-t border-outline-variant/60 space-y-3 bg-surface-container-lowest/40">
            <Link className="flex items-center justify-between text-xs text-on-surface-variant hover:text-secondary transition-colors" to="/opportunities">Explore investment opportunities <span aria-hidden="true" className="material-symbols-outlined text-base">arrow_outward</span></Link>
            <Link className="flex items-center justify-between text-xs text-on-surface-variant hover:text-secondary transition-colors" to="/backtest">Evaluate a strategy <span aria-hidden="true" className="material-symbols-outlined text-base">arrow_outward</span></Link>
          </div>
        </section>
        <section className="card xl:col-span-8 min-w-0 !p-0 overflow-hidden">
          <div className="px-5 py-4 border-b border-outline-variant/60 flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold flex items-center gap-2"><span aria-hidden="true" className="material-symbols-outlined text-on-surface-variant text-xl">history</span> Analysis History</h2>
            {data && <span className="text-xs data-font text-on-surface-variant">{total} {total === 1 ? 'run' : 'runs'}</span>}
          </div>
          {!current && <p role="status" className="py-20 text-center text-sm text-on-surface-variant">Loading analyses…</p>}
          {current?.error && <div role="alert" className="m-4 p-3 rounded border border-error/30 bg-error/5 text-sm text-error"><p>Could not refresh analyses: {current.error}</p><button className="btn-secondary mt-2" onClick={() => setVersion(value => value + 1)}>Retry</button></div>}
          {data && !jobs.length && <div className="py-20 px-6 text-center"><span aria-hidden="true" className="material-symbols-outlined text-4xl text-secondary/60 mb-3">query_stats</span><p className="text-sm font-medium">{total ? 'No analyses on this page' : 'Your research starts here'}</p><p className="text-xs text-on-surface-variant mt-2">{total ? 'Use Previous to return to earlier pages.' : 'Choose a company to generate your first investment analysis.'}</p></div>}
          {jobs.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left text-sm border-collapse">
            <thead className="bg-surface-container-high/60"><tr>{['Company', 'Status', 'Score', 'Created', ''].map(label => <th key={label} scope="col" className="px-4 py-3 text-[10px] uppercase tracking-wider font-medium text-on-surface-variant">{label || <span className="sr-only">Actions</span>}</th>)}</tr></thead>
            <tbody>{jobs.map(job => <tr key={job.analysis_id} className="border-t border-outline-variant/40 hover:bg-surface-container transition-colors">
              <td className="px-4 py-4"><Link className="group block rounded focus-visible:outline-2 focus-visible:outline-secondary" to={`/analysis/${job.analysis_id}`}><span className="font-semibold data-font group-hover:text-secondary transition-colors">{job.ticker}</span><span className="block text-[10px] text-on-surface-variant/70 data-font mt-1">{job.analysis_id.slice(0, 8)}</span></Link></td>
              <td className="px-4 py-4"><StatusChip status={job.status} /></td>
              <td className="px-4 py-4 data-font font-semibold tabular-nums">{job.investment_score != null ? Math.round(job.investment_score) : '—'}</td>
              <td className="px-4 py-4">{job.created_at ? <time dateTime={job.created_at} className="text-xs text-on-surface-variant whitespace-nowrap">{new Date(job.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}<span className="block text-[10px] data-font mt-1 opacity-70">{new Date(job.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</span></time> : '—'}</td>
              <td className="px-4 py-4">{job.can_manage ? <button className="text-xs text-on-surface-variant px-2 py-1.5 rounded border border-transparent hover:border-error/30 hover:bg-error/5 hover:text-error focus-visible:outline-2 focus-visible:outline-secondary disabled:opacity-40 disabled:cursor-wait transition-colors" disabled={pending[job.analysis_id]} onClick={() => act(job, ACTIVE.includes(job.status) ? 'cancel' : 'delete')}>{pending[job.analysis_id] ? 'Working…' : ACTIVE.includes(job.status) ? 'Cancel' : 'Delete'}</button> : <span className="text-[10px] text-on-surface-variant/70 whitespace-nowrap">Read only</span>}</td>
            </tr>)}</tbody>
          </table></div>}
          <nav aria-label="Analysis pages" className="flex items-center justify-between gap-3 px-4 py-3 border-t border-outline-variant/60 bg-surface-container-lowest/40 text-xs text-on-surface-variant">
            <button className="btn-secondary btn-sm disabled:opacity-30 disabled:cursor-not-allowed" disabled={page === 1} onClick={() => setParams({ page: String(page - 1) })}>Previous</button>
            <span>Page {page}{data ? ` of ${pages}` : ''}</span>
            <button className="btn-secondary btn-sm disabled:opacity-30 disabled:cursor-not-allowed" disabled={!data || page >= pages} onClick={() => setParams({ page: String(page + 1) })}>Next</button>
          </nav>
        </section>
      </div>

      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete analysis"
        message={`Permanently delete the ${confirmDelete?.ticker} analysis (${confirmDelete?.analysis_id})? This cannot be undone.`}
        confirmLabel="Delete"
        danger
        busy={!!confirmDelete && !!pending[confirmDelete.analysis_id]}
        onConfirm={confirmDeleteAnalysis}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
