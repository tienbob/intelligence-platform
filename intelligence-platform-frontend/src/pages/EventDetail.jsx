import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getEvent } from '../services/api';
import StatusChip from '../components/StatusChip';

export default function EventDetail() {
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
        const result = await getEvent(id);
        setItem(result);
      } catch (e) {
        setError(e.message || 'Failed to load event');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="text-on-surface-variant text-lg">Loading event...</div>
      </div>
    );
  }

  if (error || !item) {
    return (
      <div>
        <button
          onClick={() => navigate('/events')}
          className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm"
        >
          <span className="material-symbols-outlined text-sm">arrow_back</span>
          Back to Events
        </button>
        <div className="card py-16 text-center text-on-surface-variant">
          <span className="material-symbols-outlined text-5xl mb-4 block text-error">error</span>
          <p className="text-lg mb-2">Event not found</p>
          <p className="text-sm">{error || 'The requested event could not be loaded.'}</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={() => navigate('/events')}
        className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm"
      >
        <span className="material-symbols-outlined text-sm">arrow_back</span>
        Back to Events
      </button>

      {/* Event Header */}
      <div className="card mb-6">
        <div className="flex flex-col md:flex-row justify-between items-start gap-4">
          <div>
            <div className="flex items-center gap-3 flex-wrap mb-2">
              <StatusChip
                status={item.impact === 'positive' ? 'bullish' : item.impact === 'negative' ? 'bearish' : 'neutral'}
                label={item.event_type}
              />
              {item.impact && (
                <span
                  className={`text-xs font-semibold data-font ${
                    item.impact === 'positive'
                      ? 'text-tertiary'
                      : item.impact === 'negative'
                      ? 'text-error'
                      : 'text-on-surface-variant'
                  }`}
                >
                  {item.impact.toUpperCase()} IMPACT
                </span>
              )}
            </div>
            <h1 className="text-2xl font-bold text-on-surface">{item.event_type}</h1>
            {item.event_date && (
              <p className="text-sm text-on-surface-variant mt-2 data-font">
                {new Date(item.event_date).toLocaleString()}
              </p>
            )}
          </div>
          {item.company_id && (
            <div className="text-right">
              <p className="text-xs text-on-surface-variant mb-1 data-font uppercase">Company ID</p>
              <p className="text-lg font-semibold text-on-surface data-font">#{item.company_id}</p>
            </div>
          )}
        </div>
      </div>

      {/* Description */}
      {item.description && (
        <div className="card mb-6">
          <h3 className="text-lg font-semibold text-on-surface mb-3 flex items-center gap-2 border-b border-outline-variant pb-2">
            <span className="material-symbols-outlined text-primary">description</span>
            Description
          </h3>
          <p className="text-sm text-on-surface leading-relaxed">{item.description}</p>
        </div>
      )}

      {/* Score Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-gutter">
        {item.impact_score != null && (
          <div className="card">
            <p className="text-xs text-on-surface-variant mb-1 data-font uppercase">Impact Score</p>
            <p className="text-xl font-semibold text-on-surface data-font">{item.impact_score.toFixed(2)}</p>
          </div>
        )}
        {item.confidence != null && (
          <div className="card">
            <p className="text-xs text-on-surface-variant mb-1 data-font uppercase">Confidence</p>
            <p className="text-xl font-semibold text-on-surface data-font">{(item.confidence * 100).toFixed(0)}%</p>
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