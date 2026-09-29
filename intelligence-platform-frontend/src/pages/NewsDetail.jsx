import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getNewsItem } from '../services/api';

export default function NewsDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const result = await getNewsItem(id);
        setItem(result);
      } catch (e) {
        setError(e.message || 'Failed to load news item');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="text-on-surface-variant text-lg">Loading article...</div>
      </div>
    );
  }

  if (error || !item) {
    return (
      <div>
        <button
          onClick={() => navigate('/news')}
          className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm"
        >
          <span className="material-symbols-outlined text-sm">arrow_back</span>
          Back to News
        </button>
        <div className="card py-16 text-center text-on-surface-variant">
          <span className="material-symbols-outlined text-5xl mb-4 block text-error">error</span>
          <p className="text-lg mb-2">Article not found</p>
          <p className="text-sm">{error || 'The requested article could not be loaded.'}</p>
        </div>
      </div>
    );
  }

  const sentiment = item.sentiment ?? 0;

  return (
    <div>
      <button
        onClick={() => navigate('/news')}
        className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm"
      >
        <span className="material-symbols-outlined text-sm">arrow_back</span>
        Back to News
      </button>

      {/* Article Header */}
      <div className="card mb-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex-1 min-w-[240px]">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs text-on-surface-variant bg-surface-container-high px-2 py-0.5 rounded data-font">
                {item.source}
              </span>
              <span className="text-xs text-on-surface-variant data-font">
                {item.published_at ? new Date(item.published_at).toLocaleString() : '—'}
              </span>
              <div
                className={`flex items-center gap-1 px-1.5 py-0.5 rounded-sm border text-[10px] data-font ${
                  sentiment >= 0
                    ? 'bg-tertiary/10 border-tertiary/20 text-tertiary'
                    : 'bg-error/10 border-error/20 text-error'
                }`}
              >
                <div className={`w-1.5 h-1.5 rounded-full ${sentiment >= 0 ? 'bg-tertiary' : 'bg-error'}`} />
                <span>SENTIMENT {sentiment.toFixed(2)}</span>
              </div>
            </div>
            <h1 className="text-2xl font-bold text-on-surface leading-tight">{item.title}</h1>
          </div>
          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="btn-primary flex items-center gap-2 text-sm whitespace-nowrap"
            >
              <span className="material-symbols-outlined text-sm">open_in_new</span>
              View Original
            </a>
          )}
        </div>
      </div>

      {/* Summary / Body */}
      {item.summary && (
        <div className="card mb-6">
          <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
            <span className="material-symbols-outlined text-primary">article</span>
            Summary
          </h3>
          <p className="text-sm text-on-surface leading-relaxed">{item.summary}</p>
        </div>
      )}

      {/* Score Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-gutter">
        {item.relevance_score != null && (
          <div className="card">
            <p className="text-xs text-on-surface-variant mb-1 data-font uppercase">Relevance Score</p>
            <p className="text-xl font-semibold text-on-surface data-font">{item.relevance_score.toFixed(2)}</p>
          </div>
        )}
        {item.impact_score != null && (
          <div className="card">
            <p className="text-xs text-on-surface-variant mb-1 data-font uppercase">Impact Score</p>
            <p className="text-xl font-semibold text-on-surface data-font">{item.impact_score.toFixed(2)}</p>
          </div>
        )}
        {item.confidence_score != null && (
          <div className="card">
            <p className="text-xs text-on-surface-variant mb-1 data-font uppercase">Confidence</p>
            <p className="text-xl font-semibold text-on-surface data-font">{(item.confidence_score * 100).toFixed(0)}%</p>
          </div>
        )}
        {item.credibility_score != null && (
          <div className="card">
            <p className="text-xs text-on-surface-variant mb-1 data-font uppercase">Credibility</p>
            <p className="text-xl font-semibold text-on-surface data-font">{(item.credibility_score * 100).toFixed(0)}%</p>
          </div>
        )}
        {item.materiality_score != null && (
          <div className="card">
            <p className="text-xs text-on-surface-variant mb-1 data-font uppercase">Materiality</p>
            <p className="text-xl font-semibold text-on-surface data-font">{(item.materiality_score * 100).toFixed(0)}%</p>
          </div>
        )}
        {item.effective_weight != null && (
          <div className="card">
            <p className="text-xs text-on-surface-variant mb-1 data-font uppercase">Effective Weight</p>
            <p className="text-xl font-semibold text-on-surface data-font">{item.effective_weight.toFixed(2)}</p>
          </div>
        )}
      </div>
    </div>
  );
}