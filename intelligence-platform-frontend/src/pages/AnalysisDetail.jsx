import { startPolling } from '../services/polling';
import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getAnalysis, createCompanyAnalysis, cancelAnalysis, deleteAnalysis } from '../services/api';
import StatusChip from '../components/StatusChip';
import MetricTile from '../components/MetricTile';
import ConfirmDialog from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { REFRESH_ANALYSIS_DETAIL_MS } from '../config';

export default function AnalysisDetail() {
  const { analysisId } = useParams();
  const navigate = useNavigate();
  const [retryVersion, setRetryVersion] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState(null);
  const [acting, setActing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [result, setResult] = useState(null);
  const current = result?.id === analysisId ? result : null;
  const data = current?.data;
  const error = current?.error;
  const loading = !current;

  useEffect(() => {
    async function load(active) {
      let terminal = false;
      try {
        const data = await getAnalysis(analysisId);
        if (!active()) return;
        setResult({ id: analysisId, data, error: null });
        terminal = ['completed', 'failed', 'cancelled'].includes(data.status);
      } catch (e) {
        if (!active()) return;
        setResult((previous) => ({
          id: analysisId,
          data: previous?.id === analysisId ? previous.data : null,
          error: e.message || 'Failed to load analysis',
        }));
      }
      return !terminal;
    }
    return startPolling(load, REFRESH_ANALYSIS_DETAIL_MS);
  }, [analysisId, retryVersion]);

  const toast = useToast();

  async function retryAnalysis() {
    if (retrying) return;
    setRetrying(true);
    setRetryError(null);
    try {
      const created = await createCompanyAnalysis({ ...(data.request_options || {}), ticker: data.ticker });
      navigate(`/analysis/${created.analysis_id}`);
    } catch (error) {
      setRetryError(error.message || 'Could not retry. Please try again.');
    } finally {
      setRetrying(false);
    }
  }

  async function handleCancelAnalysis() {
    if (acting) return;
    setActing(true);
    try {
      const result = await cancelAnalysis(analysisId);
      toast(`Analysis ${result.status}`, 'success');
      setRetryVersion(value => value + 1);
    } catch (error) {
      toast(error.message || 'Action failed. Try again.', 'error');
    } finally {
      setActing(false);
    }
  }

  async function handleDeleteAnalysis() {
    if (acting) return;
    setConfirmDelete(false);
    setActing(true);
    try {
      await deleteAnalysis(analysisId);
      toast('Analysis deleted', 'success');
      navigate('/analysis');
    } catch (error) {
      toast(error.message || 'Action failed. Try again.', 'error');
    } finally {
      setActing(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="text-on-surface-variant text-lg">Loading analysis...</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div>
        <button
          onClick={() => navigate('/analysis')}
          className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm"
        >
          <span className="material-symbols-outlined text-sm">arrow_back</span>
          Back to AI Jobs
        </button>
        <div className="card py-16 text-center text-on-surface-variant">
          <span className="material-symbols-outlined text-5xl mb-4 block text-error">error</span>
          <p className="text-lg mb-2">Unable to load analysis</p>
          <p className="text-sm">{error || 'The requested analysis could not be loaded.'}</p>
          <button className="btn-secondary mt-4" onClick={() => setRetryVersion(value => value + 1)}>Retry loading</button>
        </div>
      </div>
    );
  }

  const analysis = data.analysis || {};
  const recommendation = data.recommendation;
  const cb = data.confidence_breakdown;
  // Owner can cancel/delete from the detail page; system rows are read-only
  // for regular users (mirrors can_manage on the jobs list).
  const canManage = !!data.can_manage;
  const isActive = !['completed', 'failed', 'cancelled'].includes(data.status);

  return (
    <div>
      {error && <p role="status" className="text-error mb-4">Refresh failed: {error}. Reload to retry.</p>}
      <button
        onClick={() => navigate('/analysis')}
        className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm"
      >
        <span className="material-symbols-outlined text-sm">arrow_back</span>
        Back to AI Jobs
      </button>

      {data.status === 'failed' && <section className="card mb-4" aria-label="Analysis failed">
        <h2 className="text-lg font-semibold">Analysis failed</h2>
        <p className="my-3">{data.failure_reason || 'This analysis did not finish. No failure details were recorded for this older job. You can start a new run.'}</p>
        {retryError && <p role="alert" className="text-error mb-2">{retryError}</p>}
        <button className="btn-primary" disabled={retrying || !data.ticker} onClick={retryAnalysis}>{retrying ? 'Starting new analysis…' : 'Retry as New Analysis'}</button>
      </section>}
      {data.status === 'cancelled' && <p role="status" className="card mb-4">This analysis was cancelled. Create a new analysis from the job list to run it again.</p>}
      {!['completed', 'failed', 'cancelled'].includes(data.status) && <p role="status" className="card mb-4">Analysis in progress. Results will appear here when processing finishes.</p>}

      {/* Header */}
      <div className="card mb-6">
        <div className="flex flex-col md:flex-row justify-between items-start gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold text-on-surface flex items-center gap-3">
                <span className="material-symbols-outlined text-secondary-container text-3xl">memory</span>
                {data.ticker || 'Analysis'}
              </h1>
              <StatusChip status={data.status} />
            </div>
            <p className="text-sm text-on-surface-variant mt-2 data-font">
              Analysis ID: <span className="text-on-surface">{data.analysis_id}</span>
            </p>
            {data.created_at && (
              <p className="text-xs text-on-surface-variant mt-1 data-font">
                Created: {new Date(data.created_at).toLocaleString()}
              </p>
            )}
          </div>
          <div className="flex flex-col items-start md:items-end gap-3">
            {recommendation && (
              <StatusChip status={recommendation.recommendation} label={`Recommendation: ${recommendation.recommendation}`} />
            )}
            {canManage && (
              <div className="flex gap-2">
                {isActive ? (
                  <button
                    className="btn-secondary btn-sm"
                    disabled={acting}
                    onClick={handleCancelAnalysis}
                  >
                    {acting ? 'Working…' : 'Cancel Analysis'}
                  </button>
                ) : (
                  <button
                    className="btn-secondary btn-sm text-error border-error/30 hover:bg-error/5"
                    disabled={acting}
                    onClick={() => setConfirmDelete(true)}
                  >
                    Delete
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Score Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-gutter mb-6">
        <MetricTile
          label="Investment Score"
          value={data.investment_score != null ? data.investment_score.toFixed(0) : '—'}
          icon="trending_up"
          color={data.investment_score > 60 ? 'tertiary' : data.investment_score > 30 ? 'secondary' : 'error'}
        />
        <MetricTile
          label="Risk Score"
          value={data.risk_score != null ? data.risk_score.toFixed(0) : '—'}
          icon="shield"
          color={data.risk_score > 60 ? 'error' : data.risk_score > 30 ? 'secondary' : 'tertiary'}
        />
        <MetricTile
          label="Data Confidence"
          value={data.confidence != null ? `${(data.confidence * 100).toFixed(0)}%` : '—'}
          icon="verified"
          color="secondary"
        />
        <MetricTile
          label="Overall Confidence"
          value={cb?.overall != null ? `${(cb.overall * 100).toFixed(0)}%` : '—'}
          icon="fact_check"
          color="tertiary"
        />
      </div>

      <div className="grid grid-cols-12 gap-gutter">
        {/* LLM Analysis (Span 8) */}
        <div className="col-span-12 lg:col-span-8 flex flex-col gap-gutter">
          {analysis.summary && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-primary">summarize</span>
                Summary
              </h3>
              <p className="text-sm text-on-surface leading-relaxed break-words">{analysis.summary}</p>
            </div>
          )}

          {analysis.investment_thesis && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-tertiary">lightbulb</span>
                Investment Thesis
              </h3>
              <p className="text-sm text-on-surface leading-relaxed break-words">{analysis.investment_thesis}</p>
            </div>
          )}

          {analysis.market_interpretation && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-secondary">public</span>
                Market Interpretation
              </h3>
              <p className="text-sm text-on-surface leading-relaxed break-words">{analysis.market_interpretation}</p>
            </div>
          )}

          {/* Bull / Bear Case */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-gutter">
            {analysis.bull_case?.length > 0 && (
              <div className="card">
                <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                  <span className="material-symbols-outlined text-tertiary">trending_up</span>
                  Bull Case
                </h3>
                <ul className="space-y-2">
                  {analysis.bull_case.map((point, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                      <span className="material-symbols-outlined text-tertiary text-base mt-0.5">check_circle</span>
                      <span className="break-words">{point}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {analysis.bear_case?.length > 0 && (
              <div className="card">
                <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                  <span className="material-symbols-outlined text-error">trending_down</span>
                  Bear Case
                </h3>
                <ul className="space-y-2">
                  {analysis.bear_case.map((point, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                      <span className="material-symbols-outlined text-error text-base mt-0.5">cancel</span>
                      <span className="break-words">{point}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Catalysts & Risks */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-gutter">
            {analysis.catalysts?.length > 0 && (
              <div className="card">
                <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                  <span className="material-symbols-outlined text-tertiary">rocket_launch</span>
                  Catalysts
                </h3>
                <ul className="space-y-2">
                  {analysis.catalysts.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                      <span className="material-symbols-outlined text-tertiary text-base mt-0.5">bolt</span>
                      <span className="break-words">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {analysis.risks?.length > 0 && (
              <div className="card">
                <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                  <span className="material-symbols-outlined text-error">warning</span>
                  Risks
                </h3>
                <ul className="space-y-2">
                  {analysis.risks.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                      <span className="material-symbols-outlined text-error text-base mt-0.5">warning</span>
                      <span className="break-words">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Causes */}
          {analysis.causes?.length > 0 && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-secondary">hub</span>
                Causes
              </h3>
              <div className="space-y-3">
                {analysis.causes.map((cause, i) => (
                  <div key={i} className="p-3 bg-surface-variant rounded border border-outline-variant">
                    <div className="flex justify-between items-start gap-2">
                      <p className="text-sm text-on-surface font-medium break-words">{cause.cause}</p>
                      <StatusChip status={cause.impact === 'high' ? 'bearish' : cause.impact === 'low' ? 'bullish' : 'neutral'} label={cause.impact} />
                    </div>
                    {cause.confidence != null && (
                      <p className="text-xs text-on-surface-variant mt-1 data-font">
                        Confidence: {(cause.confidence * 100).toFixed(0)}%
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar (Span 4) */}
        <div className="col-span-12 lg:col-span-4 flex flex-col gap-gutter">
          {/* Recommendation */}
          {recommendation && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-tertiary">recommend</span>
                Recommendation
              </h3>
              <div className="mb-4">
                <StatusChip status={recommendation.recommendation} label={recommendation.recommendation} />
              </div>
              {recommendation.reasons?.length > 0 && (
                <div className="mb-4">
                  <div className="text-xs text-on-surface-variant mb-2 data-font uppercase tracking-wider">Reasons</div>
                  <ul className="space-y-1.5">
                    {recommendation.reasons.map((r, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-on-surface">
                        <span className="material-symbols-outlined text-tertiary text-sm mt-0.5">chevron_right</span>
                        <span className="break-words">{r}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {recommendation.risks?.length > 0 && (
                <div>
                  <div className="text-xs text-on-surface-variant mb-2 data-font uppercase tracking-wider">Risks</div>
                  <ul className="space-y-1.5">
                    {recommendation.risks.map((r, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-on-surface">
                        <span className="material-symbols-outlined text-error text-sm mt-0.5">warning</span>
                        <span className="break-words">{r}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Confidence Breakdown */}
          {cb && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-secondary">fact_check</span>
                Confidence Breakdown
              </h3>
              <div className="space-y-3">
                {[
                  { label: 'Data', value: cb.data },
                  { label: 'Quantitative', value: cb.quantitative },
                  { label: 'LLM', value: cb.llm },
                  { label: 'Overall', value: cb.overall },
                ].map((item) => (
                  <div key={item.label}>
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-xs text-on-surface-variant">{item.label}</span>
                      <span className="text-sm font-semibold data-font text-on-surface">
                        {item.value != null ? `${(item.value * 100).toFixed(0)}%` : '—'}
                      </span>
                    </div>
                    <div className="w-full bg-surface-variant h-1.5 rounded-full overflow-hidden">
                      <div
                        className="bg-secondary h-full rounded-full transition-all"
                        style={{ width: `${((item.value || 0) * 100).toFixed(0)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Source-Backed Claims */}
          {data.source_backed_claims?.length > 0 && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-primary">link</span>
                Source-Backed Claims
              </h3>
              <div className="space-y-3">
                {data.source_backed_claims.map((claim, i) => (
                  <div key={i} className="p-3 bg-surface-variant rounded border border-outline-variant">
                    <p className="text-sm text-on-surface mb-2 break-words">{claim.claim}</p>
                    {claim.source && (
                      <div className="flex flex-wrap gap-1.5">
                        <span className="text-[10px] bg-surface-container-high px-1.5 py-0.5 rounded data-font text-on-surface-variant">
                          {claim.source.type}
                        </span>
                        <span className="text-[10px] bg-surface-container-high px-1.5 py-0.5 rounded data-font text-on-surface-variant">
                          {claim.source.source}
                        </span>
                        {claim.source.metric && (
                          <span className="text-[10px] bg-surface-container-high px-1.5 py-0.5 rounded data-font text-on-surface-variant">
                            {claim.source.metric}: {claim.source.value}
                          </span>
                        )}
                        {claim.source.period && (
                          <span className="text-[10px] bg-surface-container-high px-1.5 py-0.5 rounded data-font text-on-surface-variant">
                            {claim.source.period}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Invalidating Conditions */}
          {analysis.invalidating_conditions?.length > 0 && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-error">do_not_disturb</span>
                Invalidating Conditions
              </h3>
              <ul className="space-y-2">
                {analysis.invalidating_conditions.map((item, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                    <span className="material-symbols-outlined text-error text-base mt-0.5">block</span>
                    <span className="break-words">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete analysis"
        message={`Permanently delete this ${data.ticker} analysis (${data.analysis_id})? This cannot be undone.`}
        confirmLabel="Delete"
        danger
        busy={acting}
        onConfirm={handleDeleteAnalysis}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}