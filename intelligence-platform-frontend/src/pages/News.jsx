import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getNews, getMarketOverview, getEvents } from '../services/api';
import { useToast } from '../components/Toast';
import StatusChip from '../components/StatusChip';

export default function News() {
  const toast = useToast();
  const navigate = useNavigate();
  const [news, setNews] = useState([]);
  const [events, setEvents] = useState([]);
  const [vix, setVix] = useState(null);
  const [vixChange, setVixChange] = useState(null);
  const [tickerFilter, setTickerFilter] = useState('');
  const [minImpact, setMinImpact] = useState(0.5);
  // Map UI labels to actual API event type codes.
  const EVENT_TYPE_OPTIONS = {
    'Earnings': ['EARNINGS_BEAT', 'EARNINGS_MISS', 'EARNINGS_IN_LINE', 'EARNINGS_REPORT', 'GUIDANCE_UPDATE'],
    'Regulatory/Legal': ['REGULATORY', 'LEGAL', 'INSIDER_TRADING', 'INSTITUTIONAL_CHANGE'],
    'Analyst': ['ANALYST'],
    'Management': ['MANAGEMENT_CHANGE', 'DIVIDEND_CHANGE', 'STOCK_SPLIT', 'BUYBACK'],
    'Macro': ['MACRO_EVENT', 'SECTOR_EVENT'],
    'Corporate': ['PRODUCT_LAUNCH', 'MA', 'SUPPLY_CHAIN', 'OTHER'],
  };
  const [eventTypes, setEventTypes] = useState({
    'Earnings': true,
    'Regulatory/Legal': true,
    'Analyst': true,
    'Management': true,
    'Macro': true,
    'Corporate': true,
  });

  const loadData = useCallback(async () => {
    try {
      const params = { limit: 20 };
      if (tickerFilter.trim()) params.ticker = tickerFilter.trim().toUpperCase();
      const [newsData, mktData, eventsData] = await Promise.all([
        getNews(params),
        getMarketOverview(),
        getEvents({ limit: 20 }),
      ]);
      setNews(newsData?.news || []);
      // Client-side filter by event type (map selected labels → API codes) + min impact
      const allEvents = eventsData?.events || [];
      const selectedCodes = Object.entries(eventTypes)
        .filter(([, v]) => v)
        .flatMap(([label]) => EVENT_TYPE_OPTIONS[label] || []);
      const filtered = allEvents
        .filter((e) => (selectedCodes.length === 0 ? true : selectedCodes.includes(e.event_type)))
        .filter((e) => e.impact_score == null || e.impact_score >= minImpact);
      setEvents(filtered);
      const v = mktData?.macro_environment?.vix;
      setVix(v != null ? v.toFixed(2) : null);
      setVixChange(v != null && v < 20 ? 'low' : v < 30 ? 'moderate' : 'high');
    } catch {
      // API not available
    }
  }, [tickerFilter, eventTypes, minImpact]);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData();
    }, 0);
    return () => clearTimeout(timer);
  }, [loadData]);

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Market Intelligence</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Correlated news and event timelines for high-signal analysis.
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary flex items-center gap-2" onClick={() => toast('Export feature coming soon', 'info')}>
            <span className="material-symbols-outlined text-sm">download</span> Export
          </button>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-gutter">
        {/* Filters Sidebar (Span 3) */}
        <div className="col-span-12 lg:col-span-3 flex flex-col gap-gutter">
          <div className="card">
            <div className="flex items-center gap-2 mb-4 text-primary">
              <span className="material-symbols-outlined">filter_list</span>
              <h2 className="text-lg font-semibold">Intelligence Filters</h2>
            </div>
            <div className="mb-4">
              <label className="block text-xs text-on-surface-variant mb-1 data-font uppercase">
                TICKER SYMBOL
              </label>
              <input
                className="input-field uppercase data-font"
                placeholder="e.g. AAPL, MSFT"
                type="text"
                value={tickerFilter}
                onChange={(e) => setTickerFilter(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') loadData(); }}
              />
            </div>
            <div className="mb-6">
              <label className="block text-xs text-on-surface-variant mb-2 data-font uppercase">
                EVENT TYPES
              </label>
              <div className="space-y-2">
                {Object.keys(eventTypes).map((type) => (
                  <label key={type} className="flex items-center gap-2 cursor-pointer group">
                    <input
                      checked={eventTypes[type]}
                      className="rounded-sm border-outline-variant text-secondary-container focus:ring-secondary"
                      type="checkbox"
                      onChange={() => setEventTypes((prev) => ({ ...prev, [type]: !prev[type] }))}
                    />
                    <span className="text-sm text-on-surface group-hover:text-primary transition-colors">
                      {type}
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-xs text-on-surface-variant mb-2 flex justify-between data-font">
                <span>MIN IMPACT SCORE</span>
                <span className="text-tertiary">{minImpact.toFixed(2)}</span>
              </label>
              <input
                className="w-full accent-tertiary h-1 bg-surface-variant rounded-full appearance-none cursor-pointer"
                max="1"
                min="0"
                step="0.05"
                type="range"
                value={minImpact}
                onChange={(e) => setMinImpact(Number(e.target.value))}
              />
            </div>
          </div>

          {/* VIX Widget */}
          <div className="card flex flex-col items-center justify-center py-8">
            <div className="text-sm text-on-surface-variant mb-1 data-font">VIX INDEX</div>
            <div className="text-4xl font-bold text-on-surface data-font">{vix || '—'}</div>
            <div className={`text-sm flex items-center gap-1 mt-1 data-font ${vixChange === 'low' ? 'text-tertiary' : vixChange === 'high' ? 'text-error' : 'text-secondary'}`}>
              <span className="material-symbols-outlined text-base">
                {vixChange === 'low' ? 'arrow_downward' : vixChange === 'high' ? 'arrow_upward' : 'trending_flat'}
              </span>
              {vixChange || '—'}
            </div>
          </div>
        </div>

        {/* Event Timeline (Span 5) */}
        <div className="col-span-12 lg:col-span-5 flex flex-col gap-gutter">
          <div className="card flex-1 flex flex-col">
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-lg font-semibold text-on-surface flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary">timeline</span>
                Event Timeline
              </h2>
            </div>
            <div className="relative pl-6 border-l border-outline-variant space-y-6 flex-1 overflow-y-auto pr-2">
              {events.length > 0 ? (
                events.slice(0, 8).map((event) => (
                 <div key={event.id} className="relative group cursor-pointer">
                    <div className={`absolute -left-[29px] top-1 w-3 h-3 rounded-full ring-4 ring-surface-container-low ${event.impact === 'positive' ? 'bg-secondary' : event.impact === 'negative' ? 'bg-error' : 'bg-surface-variant border border-outline-variant'}`} />
                    <div className="bg-surface-container-high border border-outline-variant rounded p-3 group-hover:border-secondary transition-colors">
                      <div className="flex justify-between items-start mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-on-surface bg-primary-fixed text-on-primary-fixed px-1.5 py-0.5 rounded-sm uppercase data-font">
                            {event.ticker || 'SYS'}
                          </span>
                          <span className="text-xs text-on-surface-variant">
                            {event.event_date ? new Date(event.event_date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                          </span>
                        </div>
                        <StatusChip status={event.impact === 'positive' ? 'bullish' : event.impact === 'negative' ? 'bearish' : 'neutral'} label={event.event_type} />
                      </div>
                      <p className="text-sm font-semibold leading-tight text-on-surface mb-2">{event.description}</p>
                      {event.impact_score != null && (
                        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-outline-variant/50">
                          <div className="flex flex-col">
                            <span className="text-[10px] text-on-surface-variant data-font">IMPACT SCORE</span>
                            <span className="text-sm text-tertiary data-font">{event.impact_score?.toFixed(2)}</span>
                          </div>
                          <div className="flex flex-col border-l border-outline-variant pl-4">
                            <span className="text-[10px] text-on-surface-variant data-font">CONFIDENCE</span>
                            <span className="text-sm text-on-surface data-font">{event.confidence ? `${(event.confidence * 100).toFixed(0)}%` : '—'}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className="py-12 text-center text-on-surface-variant">
                  <span className="material-symbols-outlined text-4xl mb-2 block">timeline</span>
                  <p>No events detected yet.</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Correlated News Feed (Span 4) */}
        <div className="col-span-12 lg:col-span-4 flex flex-col gap-gutter">
          <div className="card flex-1 flex flex-col">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold text-on-surface flex items-center gap-2">
                <span className="material-symbols-outlined text-primary">feed</span>
                Correlated News
              </h2>
            </div>
            <div className="space-y-3 flex-1 overflow-y-auto">
              {news.length > 0 ? (
                news.map((article) => (
                  <div
                    key={article.id}
                    onClick={() => navigate(`/news/${article.id}`)}
                    className="p-3 bg-surface-container rounded border border-transparent hover:border-outline-variant transition-colors group cursor-pointer"
                  >
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-xs text-on-surface-variant data-font">
                        {article.source} &bull; {new Date(article.published_at).toLocaleDateString()}
                      </span>
                      <div
                        className={`flex items-center gap-1 px-1.5 py-0.5 rounded-sm border text-[10px] data-font ${
                          (article.sentiment || 0) >= 0
                            ? 'bg-tertiary/10 border-tertiary/20 text-tertiary'
                            : 'bg-error/10 border-error/20 text-error'
                        }`}
                      >
                        <div
                          className={`w-1.5 h-1.5 rounded-full ${
                            (article.sentiment || 0) >= 0 ? 'bg-tertiary' : 'bg-error'
                          }`}
                        />
                        <span>SENTIMENT {article.sentiment?.toFixed(2) || '0.00'}</span>
                      </div>
                    </div>
                    <h3 className="text-sm font-semibold text-on-surface mb-1 group-hover:text-primary transition-colors">
                      {article.title}
                    </h3>
                    <p className="text-xs text-on-surface-variant line-clamp-2">{article.summary}</p>
                  </div>
                ))
              ) : (
                <div className="py-12 text-center text-on-surface-variant">
                  <span className="material-symbols-outlined text-4xl mb-2 block">feed</span>
                  <p>No news articles available.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}