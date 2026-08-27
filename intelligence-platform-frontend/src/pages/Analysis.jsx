import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { createCompanyAnalysis, getAnalysisJobs, deleteAnalysis } from "../services/api";
import { useToast } from "../components/Toast";
import StatusChip from "../components/StatusChip";
import ProgressBar from "../components/ProgressBar";
import { REFRESH_ANALYSIS_JOBS_MS } from "../config";

export default function Analysis() {
  const toast = useToast();
  const navigate = useNavigate();
  const [ticker, setTicker] = useState("");
  const [timeHorizon, setTimeHorizon] = useState("medium_term");
  const [includeNews, setIncludeNews] = useState(true);
  const [includeFundamentals, setIncludeFundamentals] = useState(true);
  const [includeTechnical, setIncludeTechnical] = useState(true);
  const [includeMacro, setIncludeMacro] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  async function loadJobs() {
    try {
      const data = await getAnalysisJobs({ limit: 20 });
      setJobs(data?.jobs || []);
    } catch {
      // API not available
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadJobs(); }, []);

  // Auto-refresh the job list while jobs are active (running/queued), so the
  // UI updates when an AI analysis finishes without a manual refresh.
  useEffect(() => {
    if (REFRESH_ANALYSIS_JOBS_MS <= 0) return;
    const interval = setInterval(() => {
      loadJobs();
    }, REFRESH_ANALYSIS_JOBS_MS);
    return () => clearInterval(interval);
  }, []);

  const activeStatuses = ["queued", "collecting_data", "calculating_metrics", "retrieving_context", "llm_analysis", "risk_analysis", "running", "processing"];

  async function handleCancel(analysisId) {
    try {
      await deleteAnalysis(analysisId);
      toast("Analysis job cancelled", "success");
      await loadJobs();
    } catch (err) {
      toast(err.message || "Failed to cancel analysis", "error");
    }
  }

  async function handleDelete(analysisId) {
    try {
      await deleteAnalysis(analysisId);
      toast("Analysis record deleted", "success");
      await loadJobs();
    } catch (err) {
      toast(err.message || "Failed to delete analysis", "error");
    }
  }

  async function handleCreate() {
    if (!ticker.trim()) return;
    setSubmitting(true);
    try {
      const data = await createCompanyAnalysis({
        ticker: ticker.trim().toUpperCase(),
        time_horizon: timeHorizon,
        include_news: includeNews,
        include_fundamentals: includeFundamentals,
        include_technical: includeTechnical,
        include_macro: includeMacro,
      });
      setResult(data);
      toast(`Analysis queued: ${data.analysis_id?.slice(0, 8)}...`, "success");
      setTicker("");
      // Refresh job list
      await loadJobs();
    } catch (err) {
      // Surface the actual backend error (e.g. "Company APPL not found")
      // instead of a generic "backend unavailable" message.
      setResult({ status: "error", message: err.message || "Analysis failed to start" });
    } finally {
      setSubmitting(false);
    }
  }

  const activeCount = jobs.filter(j => activeStatuses.includes(j.status)).length;
  const completedCount = jobs.filter(j => j.status === "completed").length;
  const failedCount = jobs.filter(j => j.status === "failed").length;

  return (
    <div>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface flex items-center gap-2">
            <span className="material-symbols-outlined text-secondary-container text-3xl">memory</span>
            AI Analysis Jobs
          </h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Manage and monitor parallel execution of financial intelligence models.
          </p>
        </div>
        <p className="text-sm text-on-surface-variant mt-1">{REFRESH_ANALYSIS_JOBS_MS > 0 ? `Auto-refreshes every ${REFRESH_ANALYSIS_JOBS_MS / 1000}s.` : ''}</p>
      </div>

      {result && (
        <div className={`mb-6 p-4 rounded border text-sm ${result.status === "error" ? "bg-error-container/20 border-error-container/50 text-error" : "bg-tertiary-fixed/10 border-tertiary-fixed/30 text-tertiary"}`}>
          {result.analysis_id ? `Analysis created: ${result.analysis_id} (${result.status})` : result.message || "Analysis submitted"}
        </div>
      )}

      {/* Metrics Row — Real Data */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-gutter mb-6">
        <div className="card flex flex-col items-center justify-center py-6">
          <span className="material-symbols-outlined text-3xl text-tertiary mb-2">rocket_launch</span>
          <span className="text-xs text-on-surface-variant">Active/Queued</span>
          <span className="text-2xl font-bold text-on-surface data-font mt-1">{activeCount || '—'}</span>
        </div>
        <div className="card flex flex-col items-center justify-center py-6">
          <span className="material-symbols-outlined text-3xl text-on-surface-variant mb-2">hourglass_empty</span>
          <span className="text-xs text-on-surface-variant">Total Jobs</span>
          <span className="text-2xl font-bold text-on-surface data-font mt-1">{jobs.length || '—'}</span>
        </div>
        <div className="card flex flex-col items-center justify-center py-6">
          <span className="material-symbols-outlined text-3xl text-tertiary mb-2">task_alt</span>
          <span className="text-xs text-on-surface-variant">Completed</span>
          <span className="text-2xl font-bold text-on-surface data-font mt-1">{completedCount || '—'}</span>
        </div>
        <div className="card flex flex-col items-center justify-center py-6">
          <span className="material-symbols-outlined text-3xl text-error mb-2">error</span>
          <span className="text-xs text-on-surface-variant">Failed</span>
          <span className="text-2xl font-bold text-on-surface data-font mt-1">{failedCount || '—'}</span>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-gutter">
        {/* Execution Queue */}
        <div className="col-span-12 lg:col-span-8 card flex flex-col overflow-hidden !p-0 h-[600px]">
          <div className="px-4 py-3 border-b border-outline-variant flex justify-between items-center bg-surface-container-lowest">
            <h2 className="text-lg font-semibold text-on-surface flex items-center gap-2">
              <span className="material-symbols-outlined text-on-surface-variant">list_alt</span>
              Execution Queue
            </h2>
          </div>
          <div className="flex-1 overflow-auto">
            {jobs.length > 0 ? (
              <table className="w-full text-left border-collapse">
                <thead className="sticky top-0 bg-surface-container-highest border-b border-outline-variant z-10 shadow-sm">
                  <tr>
                    <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">JOB ID</th>
                    <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">TICKER</th>
                    <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">STATUS</th>
                    <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">SCORE</th>
                    <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold text-right">ACTIONS</th>
                  </tr>
                </thead>
                <tbody className="text-sm data-font divide-y divide-surface-variant">
                  {jobs.map((job, i) => (
                    <tr
                      key={job.id}
                      onClick={() => navigate(`/analysis/${job.analysis_id}`)}
                      className={`cursor-pointer hover:bg-surface-variant/50 transition-colors group ${i % 2 === 0 ? "bg-surface-dim/30" : ""} ${job.status === "completed" ? "border-l-2 border-l-tertiary" : ""} ${job.status === "failed" ? "border-l-2 border-l-error" : ""}`}
                    >
                      <td className="py-3 px-4 text-on-surface-variant text-xs">{job.analysis_id?.slice(0, 12)}...</td>
                      <td className="py-3 px-4 font-bold">{job.ticker || '—'}</td>
                      <td className="py-3 px-4"><StatusChip status={job.status} /></td>
                      <td className="py-3 px-4">
                        {job.investment_score != null ? (
                          <ProgressBar value={job.investment_score} max={100} color={job.investment_score > 60 ? 'tertiary' : job.investment_score > 30 ? 'secondary' : 'error'} showLabel={false} />
                        ) : '—'}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <span className="text-on-surface-variant text-xs">
                            {job.created_at ? new Date(job.created_at).toLocaleString() : '—'}
                          </span>
                          {activeStatuses.includes(job.status) ? (
                            <button
                              className="opacity-0 group-hover:opacity-100 transition-opacity px-2 py-1 bg-surface-container-highest border border-outline-variant hover:border-warning hover:text-warning text-on-surface-variant rounded text-xs"
                              onClick={(e) => { e.stopPropagation(); handleCancel(job.analysis_id); }}
                              title="Cancel this analysis job"
                            >
                              <span className="material-symbols-outlined text-sm">cancel</span>
                            </button>
                          ) : (
                            <button
                              className="opacity-0 group-hover:opacity-100 transition-opacity px-2 py-1 bg-surface-container-highest border border-outline-variant hover:border-error hover:text-error text-on-surface-variant rounded text-xs"
                              onClick={(e) => { e.stopPropagation(); handleDelete(job.analysis_id); }}
                              title="Delete this analysis record"
                            >
                              <span className="material-symbols-outlined text-sm">delete</span>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
                <span className="material-symbols-outlined text-5xl mb-4">list_alt</span>
                <p className="text-sm">No analysis jobs yet.</p>
                <p className="text-xs mt-1">Create one using the form on the right.</p>
              </div>
            )}
          </div>
        </div>

        {/* Side Panel */}
        <div className="col-span-12 lg:col-span-4 flex flex-col gap-gutter">
          {/* Deploy New Agent */}
          <div className="card relative overflow-hidden group">
            <div className="absolute -right-10 -top-10 w-32 h-32 bg-secondary-container/10 rounded-full blur-2xl group-hover:bg-secondary-container/20 transition-all" />
            <h3 className="text-lg font-semibold text-on-surface mb-2 relative z-10">Deploy New Agent</h3>
            <p className="text-xs text-on-surface-variant mb-4 relative z-10">
              Initialize a bespoke ML pipeline for targeted asset analysis.
            </p>
            <div className="space-y-3 relative z-10">
              <div>
                <label className="block text-xs text-on-surface-variant mb-1 uppercase tracking-wider data-font">Target Entity</label>
                <input className="input-field uppercase data-font" placeholder="Ticker (e.g. AAPL)" type="text" value={ticker} onChange={(e) => setTicker(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs text-on-surface-variant mb-1 uppercase tracking-wider data-font">Time Horizon</label>
                <select className="select-field" value={timeHorizon} onChange={(e) => setTimeHorizon(e.target.value)}>
                  <option value="short_term">Short Term</option>
                  <option value="medium_term">Medium Term</option>
                  <option value="long_term">Long Term</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-on-surface-variant mb-1 uppercase tracking-wider data-font">Data Inclusions</label>
                <div className="space-y-1.5">
                  {[
                    { key: 'news', label: 'News', set: setIncludeNews, val: includeNews },
                    { key: 'fundamentals', label: 'Fundamentals', set: setIncludeFundamentals, val: includeFundamentals },
                    { key: 'technical', label: 'Technical', set: setIncludeTechnical, val: includeTechnical },
                    { key: 'macro', label: 'Macro', set: setIncludeMacro, val: includeMacro },
                  ].map((opt) => (
                    <label key={opt.key} className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        className="rounded-sm border-outline-variant text-secondary-container focus:ring-secondary"
                        checked={opt.val}
                        onChange={(e) => opt.set(e.target.checked)}
                      />
                      <span className="text-sm text-on-surface">{opt.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              <button className="w-full py-2 bg-primary-container border border-secondary-container/50 text-secondary-fixed hover:bg-secondary-container/10 text-xs font-semibold tracking-wide rounded transition-colors mt-2 uppercase flex items-center justify-center gap-2 data-font" onClick={handleCreate} disabled={submitting}>
                <span className="material-symbols-outlined text-sm">bolt</span>
                {submitting ? "Initializing..." : "Initialize Run"}
              </button>
            </div>
          </div>

          {/* Investment Opportunities Summary */}
          <div className="card">
            <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-tertiary">insights</span>
              Quick Actions
            </h3>
            <div className="space-y-2">
              <a href="/portfolio" className="block p-3 bg-surface-variant border border-outline-variant rounded hover:bg-surface-bright hover:border-secondary transition-colors group">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary">pie_chart</span>
                  <span className="text-sm text-on-surface">View Investment Opportunities</span>
                </div>
                <p className="text-xs text-on-surface-variant mt-1">See scored recommendations and optimize portfolio allocation.</p>
              </a>
              <a href="/backtest" className="block p-3 bg-surface-variant border border-outline-variant rounded hover:bg-surface-bright hover:border-secondary transition-colors group">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary">history</span>
                  <span className="text-sm text-on-surface">Run Backtest</span>
                </div>
                <p className="text-xs text-on-surface-variant mt-1">Evaluate strategy performance against historical data.</p>
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}