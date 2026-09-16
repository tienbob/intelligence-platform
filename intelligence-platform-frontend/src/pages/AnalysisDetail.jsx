import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getAnalysis } from '../services/api';
import StatusChip from '../components/StatusChip';
import MetricTile from '../components/MetricTile';
import { REFRESH_ANALYSIS_DETAIL_MS } from '../config';

export default function AnalysisDetail() {
  const { analysisId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const result = await getAnalysis(analysisId);
        if (cancelled) return;
        setData(result);
      } catch (e) {
        if (cancelled) return;
        setError(e.message || 'Failed to load analysis');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();

    // Auto-refresh while the job is still active (queued/running/llm_analysis)
    // so the page updates when the AI analysis finishes. Stops polling once
    // the analysis reaches a terminal status (completed/failed).
    let interval = null;
    if (REFRESH_ANALYSIS_DETAIL_MS > 0) {
      interval = setInterval(() => {
        if (data && ['completed', 'failed'].includes(data.status)) {
          clearInterval(interval);
          return;
        }
        load();
      }, REFRESH_ANALYSIS_DETAIL_MS);
    }

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [analysisId, data?.status]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="text-on-surface-variant text-lg">Loading analysis...</div>
      </div>
    );
  }

  if (error || !data) {
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
          <p className="text-lg mb-2">Analysis not found</p>
          <p className="text-sm">{error || 'The requested analysis could not be loaded.'}</p>
        </div>
      </div>
    );
  }

  const analysis = data.analysis || {};
  const recommendation = data.recommendation;
  const cb = data.confidence_breakdown;

  return (
    <div>
      <button
        onClick={() => navigate('/analysis')}
        className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm"
      >
        <span className="material-symbols-outlined text-sm">arrow_back</span>
        Back to AI Jobs
      </button>

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
          {recommendation && (
            <div className="text-right">
              <StatusChip status={recommendation.recommendation} label={`Recommendation: ${recommendation.recommendation}`} />
            </div>
          )}
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
          label="Confidence"
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
              <p className="text-sm text-on-surface leading-relaxed line-clamp-4">{analysis.summary}</p>
            </div>
          )}

          {analysis.investment_thesis && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-tertiary">lightbulb</span>
                Investment Thesis
              </h3>
              <p className="text-sm text-on-surface leading-relaxed line-clamp-4">{analysis.investment_thesis}</p>
            </div>
          )}

          {analysis.market_interpretation && (
            <div className="card">
              <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-secondary">public</span>
                Market Interpretation
              </h3>
              <p className="text-sm text-on-surface leading-relaxed line-clamp-4">{analysis.market_interpretation}</p>
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
                  {analysis.bull_case.slice(0, 4).map((point, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                      <span className="material-symbols-outlined text-tertiary text-base mt-0.5">check_circle</span>
                      <span className="line-clamp-2">{point}</span>
                    </li>
                  ))}
                </ul>
                {analysis.bull_case.length > 4 && (
                  <p className="text-xs text-on-surface-variant mt-2 italic">+{analysis.bull_case.length - 4} more</p>
                )}
              </div>
            )}
            {analysis.bear_case?.length > 0 && (
              <div className="card">
                <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                  <span className="material-symbols-outlined text-error">trending_down</span>
                  Bear Case
                </h3>
                <ul className="space-y-2">
                  {analysis.bear_case.slice(0, 4).map((point, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                      <span className="material-symbols-outlined text-error text-base mt-0.5">cancel</span>
                      <span className="line-clamp-2">{point}</span>
                    </li>
                  ))}
                </ul>
                {analysis.bear_case.length > 4 && (
                  <p className="text-xs text-on-surface-variant mt-2 italic">+{analysis.bear_case.length - 4} more</p>
                )}
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
                  {analysis.catalysts.slice(0, 4).map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                      <span className="material-symbols-outlined text-tertiary text-base mt-0.5">bolt</span>
                      <span className="line-clamp-2">{item}</span>
                    </li>
                  ))}
                </ul>
                {analysis.catalysts.length > 4 && (
                  <p className="text-xs text-on-surface-variant mt-2 italic">+{analysis.catalysts.length - 4} more</p>
                )}
              </div>
            )}
            {analysis.risks?.length > 0 && (
              <div className="card">
                <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
                  <span className="material-symbols-outlined text-error">warning</span>
                  Risks
                </h3>
                <ul className="space-y-2">
                  {analysis.risks.slice(0, 4).map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                      <span className="material-symbols-outlined text-error text-base mt-0.5">warning</span>
                      <span className="line-clamp-2">{item}</span>
                    </li>
                  ))}
                </ul>
                {analysis.risks.length > 4 && (
                  <p className="text-xs text-on-surface-variant mt-2 italic">+{analysis.risks.length - 4} more</p>
                )}
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
                {analysis.causes.slice(0, 3).map((cause, i) => (
                  <div key={i} className="p-3 bg-surface-variant rounded border border-outline-variant">
                    <div className="flex justify-between items-start gap-2">
                      <p className="text-sm text-on-surface font-medium line-clamp-2">{cause.cause}</p>
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
              {analysis.causes.length > 3 && (
                <p className="text-xs text-on-surface-variant mt-2 italic">+{analysis.causes.length - 3} more</p>
              )}
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
                    {recommendation.reasons.slice(0, 3).map((r, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-on-surface">
                        <span className="material-symbols-outlined text-tertiary text-sm mt-0.5">chevron_right</span>
                        <span className="line-clamp-1">{r}</span>
                      </li>
                    ))}
                  </ul>
                  {recommendation.reasons.length > 3 && (
                    <p className="text-xs text-on-surface-variant mt-1 italic">+{recommendation.reasons.length - 3} more</p>
                  )}
                </div>
              )}
              {recommendation.risks?.length > 0 && (
                <div>
                  <div className="text-xs text-on-surface-variant mb-2 data-font uppercase tracking-wider">Risks</div>
                  <ul className="space-y-1.5">
                    {recommendation.risks.slice(0, 3).map((r, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-on-surface">
                        <span className="material-symbols-outlined text-error text-sm mt-0.5">warning</span>
                        <span className="line-clamp-1">{r}</span>
                      </li>
                    ))}
                  </ul>
                  {recommendation.risks.length > 3 && (
                    <p className="text-xs text-on-surface-variant mt-1 italic">+{recommendation.risks.length - 3} more</p>
                  )}
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
                {data.source_backed_claims.slice(0, 3).map((claim, i) => (
                  <div key={i} className="p-3 bg-surface-variant rounded border border-outline-variant">
                    <p className="text-sm text-on-surface mb-2 line-clamp-2">{claim.claim}</p>
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
              {data.source_backed_claims.length > 3 && (
                <p className="text-xs text-on-surface-variant mt-2 italic">+{data.source_backed_claims.length - 3} more</p>
              )}
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
                {analysis.invalidating_conditions.slice(0, 3).map((item, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                    <span className="material-symbols-outlined text-error text-base mt-0.5">block</span>
                    <span className="line-clamp-2">{item}</span>
                  </li>
                ))}
              </ul>
              {analysis.invalidating_conditions.length > 3 && (
                <p className="text-xs text-on-surface-variant mt-2 italic">+{analysis.invalidating_conditions.length - 3} more</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}