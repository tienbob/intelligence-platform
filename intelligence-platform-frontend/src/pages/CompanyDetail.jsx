import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getStockQuote,
  getStockPrices,
  getFinancialStatements,
  getFinancialMetrics,
  getTechnicalIndicators,
} from '../services/api';

export default function CompanyDetail() {
  const { ticker } = useParams();
  const navigate = useNavigate();
  const [quote, setQuote] = useState(null);
  const [prices, setPrices] = useState([]);
  const [statements, setStatements] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [technicals, setTechnicals] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      setNotFound(false);
      try {
        const [q, p, s, m, t] = await Promise.allSettled([
          getStockQuote(ticker),
          getStockPrices(ticker, { limit: 90 }),
          getFinancialStatements(ticker, { limit: 4 }),
          getFinancialMetrics(ticker),
          getTechnicalIndicators(ticker),
        ]);

        // The quote is the core request: the backend returns 404 when the
        // company doesn't exist OR is outside the requester's granted
        // companies (user_companies scoping). Promise.allSettled swallows
        // rejections, so surface that case explicitly instead of silently
        // rendering an empty page.
        if (q.status === 'rejected') {
          if (q.reason?.status === 404) {
            setNotFound(true);
            return;
          }
          setError(q.reason?.message || 'Failed to load company data');
        }

        setQuote(q.status === 'fulfilled' ? q.value : null);
        setPrices(p.status === 'fulfilled' ? p.value?.prices || [] : []);
        setStatements(s.status === 'fulfilled' ? s.value || [] : []);
        setMetrics(m.status === 'fulfilled' ? m.value : null);
        setTechnicals(t.status === 'fulfilled' ? t.value : null);
      } catch {
        setError('Failed to load company data');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [ticker]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="text-on-surface-variant text-lg">Loading {ticker}...</div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div>
        <button
          onClick={() => navigate('/companies')}
          className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm"
        >
          <span className="material-symbols-outlined text-sm">arrow_back</span>
          Back to Companies
        </button>
        <div className="card py-16 text-center text-on-surface-variant">
          <span className="material-symbols-outlined text-5xl mb-4 block text-error">block</span>
          <p className="text-lg mb-2 text-on-surface">{ticker} is not available</p>
          <p className="text-sm max-w-md mx-auto">
            This company isn&apos;t part of your assigned portfolio, or it
            doesn&apos;t exist. Ask your administrator for access if you need it.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Back button */}
      <button
        onClick={() => navigate('/companies')}
        className="text-on-surface-variant hover:text-on-surface transition-colors mb-4 flex items-center gap-1 text-sm"
      >
        <span className="material-symbols-outlined text-sm">arrow_back</span>
        Back to Companies
      </button>

      {/* Stock Quote Header */}
      {quote && (
        <div className="card mb-6">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 bg-surface-container rounded flex items-center justify-center border border-outline-variant">
              <span className="text-3xl font-bold text-on-surface data-font">{ticker[0]}</span>
            </div>
            <div>
              <h1 className="text-3xl font-bold text-on-surface">{quote.name || ticker}</h1>
              <span className="text-sm text-on-surface-variant bg-surface-container-high px-2 py-0.5 rounded data-font">
                {ticker}
              </span>
            </div>
            <div className="ml-auto text-right">
              <div className="text-3xl font-bold text-on-surface data-font">
                ${quote.price?.toFixed(2) || '—'}
              </div>
              <div
                className={`text-sm flex items-center justify-end gap-1 data-font ${
                  (quote.change_percent || 0) >= 0 ? 'text-tertiary' : 'text-error'
                }`}
              >
                <span className="material-symbols-outlined text-sm">
                  {(quote.change_percent || 0) >= 0 ? 'arrow_upward' : 'arrow_downward'}
                </span>
                {quote.change_percent != null ? `${quote.change_percent.toFixed(2)}%` : '—'}
                {quote.change != null
                  ? ` (${quote.change >= 0 ? '+' : ''}${quote.change.toFixed(2)})`
                  : ''}
              </div>
              <div className="text-xs text-on-surface-variant mt-1 data-font">
                Vol: {quote.volume?.toLocaleString() || '—'}
              </div>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 rounded border bg-error-container/20 border-error-container/50 text-error">
          <p className="text-sm">{error}</p>
        </div>
      )}

      <div className="grid grid-cols-12 gap-gutter">
        {/* Price Chart (Span 8) */}
        <div className="col-span-12 lg:col-span-8 card">
          <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
            <span className="material-symbols-outlined text-secondary">show_chart</span>
            Price History
            <span className="text-xs text-on-surface-variant font-normal ml-2 data-font">
            </span>
          </h3>
          {prices.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm data-font">
                <thead>
                  <tr className="bg-surface-container-highest border-b border-outline-variant">
                    <th className="py-1.5 px-3 text-xs text-on-surface-variant">Date</th>
                    <th className="py-1.5 px-3 text-xs text-on-surface-variant text-right">Open</th>
                    <th className="py-1.5 px-3 text-xs text-on-surface-variant text-right">High</th>
                    <th className="py-1.5 px-3 text-xs text-on-surface-variant text-right">Low</th>
                    <th className="py-1.5 px-3 text-xs text-on-surface-variant text-right">Close</th>
                    <th className="py-1.5 px-3 text-xs text-on-surface-variant text-right">Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {prices.slice(-20).reverse().map((p, i) => (
                    <tr
                      key={i}
                      className={`${i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'} border-b border-outline-variant`}
                    >
                      <td className="py-1.5 px-3 text-on-surface-variant">
                        {new Date(p.timestamp).toLocaleDateString()}
                      </td>
                      <td className="py-1.5 px-3 text-right">${p.open?.toFixed(2)}</td>
                      <td className="py-1.5 px-3 text-right">${p.high?.toFixed(2)}</td>
                      <td className="py-1.5 px-3 text-right">${p.low?.toFixed(2)}</td>
                      <td className="py-1.5 px-3 text-right font-semibold">${p.close?.toFixed(2)}</td>
                      <td className="py-1.5 px-3 text-right text-on-surface-variant">
                        {(p.volume / 1e6).toFixed(1)}M
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-8 text-center text-on-surface-variant">
              <span className="material-symbols-outlined text-4xl mb-2 block">show_chart</span>
              <p>No price data available.</p>
            </div>
          )}
        </div>

        {/* Technical Indicators (Span 4) */}
        <div className="col-span-12 lg:col-span-4 card">
          <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
            <span className="material-symbols-outlined text-tertiary">query_stats</span>
            Technical Indicators
            <span className="text-xs text-on-surface-variant font-normal ml-2 data-font">
            </span>
          </h3>
          {technicals ? (
            <div className="space-y-3">
              {[
                { label: 'RSI (14)', value: technicals.rsi_14?.toFixed(1), color: technicals.rsi_14 > 70 ? 'text-error' : technicals.rsi_14 < 30 ? 'text-tertiary' : 'text-on-surface' },
                { label: 'MACD', value: technicals.macd?.toFixed(2), color: 'text-on-surface' },
                { label: 'MACD Signal', value: technicals.macd_signal?.toFixed(2), color: 'text-on-surface' },
                { label: 'SMA 20', value: technicals.sma_20 ? `$${technicals.sma_20.toFixed(2)}` : '—', color: 'text-on-surface' },
                { label: 'SMA 50', value: technicals.sma_50 ? `$${technicals.sma_50.toFixed(2)}` : '—', color: 'text-on-surface' },
                { label: 'SMA 200', value: technicals.sma_200 ? `$${technicals.sma_200.toFixed(2)}` : '—', color: 'text-on-surface' },
                { label: 'Bollinger Upper', value: technicals.bollinger_upper ? `$${technicals.bollinger_upper.toFixed(2)}` : '—', color: 'text-on-surface' },
                { label: 'Bollinger Lower', value: technicals.bollinger_lower ? `$${technicals.bollinger_lower.toFixed(2)}` : '—', color: 'text-on-surface' },
                { label: 'ATR', value: technicals.atr?.toFixed(2), color: 'text-on-surface' },
                { label: 'Volatility (30d)', value: technicals.volatility_30d ? `${(technicals.volatility_30d * 100).toFixed(1)}%` : '—', color: 'text-on-surface' },
                { label: 'Momentum', value: technicals.momentum?.toFixed(2), color: 'text-on-surface' },
                { label: 'Max Drawdown', value: technicals.drawdown ? `${(technicals.drawdown * 100).toFixed(1)}%` : '—', color: 'text-error' },
              ].map((item) => (
                <div key={item.label} className="flex justify-between items-center py-1 border-b border-outline-variant/30">
                  <span className="text-xs text-on-surface-variant">{item.label}</span>
                  <span className={`text-sm font-semibold data-font ${item.color}`}>{item.value || '—'}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-8 text-center text-on-surface-variant">
              <span className="material-symbols-outlined text-4xl mb-2 block">query_stats</span>
              <p>No technical data available. Run technical analysis first.</p>
            </div>
          )}
        </div>

        {/* Financial Statements (Span 8) */}
        <div className="col-span-12 lg:col-span-8 card overflow-hidden !p-0">
          <div className="p-widget-padding border-b border-outline-variant bg-surface-container-low">
            <h3 className="text-lg font-semibold text-on-surface flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">description</span>
              Financial Statements
              <span className="text-xs text-on-surface-variant font-normal ml-2 data-font">
              </span>
            </h3>
          </div>
          {statements.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm data-font">
                <thead>
                  <tr className="bg-surface-container-highest border-b border-outline-variant">
                    <th className="py-2 px-3 text-xs text-on-surface-variant">Period</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant text-right">Revenue</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant text-right">Gross Profit</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant text-right">Op. Income</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant text-right">Net Income</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant text-right">EPS</th>
                    <th className="py-2 px-3 text-xs text-on-surface-variant text-right">FCF</th>
                  </tr>
                </thead>
                <tbody>
                  {statements.map((s, i) => (
                    <tr
                      key={s.id}
                      className={`${i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'} border-b border-outline-variant`}
                    >
                      <td className="py-2 px-3 font-semibold">{s.period}</td>
                      <td className="py-2 px-3 text-right">${(s.revenue / 1e9).toFixed(1)}B</td>
                      <td className="py-2 px-3 text-right">${(s.gross_profit / 1e9).toFixed(1)}B</td>
                      <td className="py-2 px-3 text-right">${(s.operating_income / 1e9).toFixed(1)}B</td>
                      <td className="py-2 px-3 text-right">${(s.net_income / 1e9).toFixed(1)}B</td>
                      <td className="py-2 px-3 text-right">${s.eps?.toFixed(2)}</td>
                      <td className="py-2 px-3 text-right">${(s.free_cash_flow / 1e9).toFixed(1)}B</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-12 text-center text-on-surface-variant">
              <span className="material-symbols-outlined text-4xl mb-2 block">description</span>
              <p>No financial statements available.</p>
            </div>
          )}
        </div>

        {/* Financial Metrics (Span 4) */}
        <div className="col-span-12 lg:col-span-4 card">
          <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2 border-b border-outline-variant pb-2">
            <span className="material-symbols-outlined text-secondary">calculate</span>
            Financial Metrics
            <span className="text-xs text-on-surface-variant font-normal ml-2 data-font">
            </span>
          </h3>
          {metrics ? (
            <div className="space-y-3">
              <div className="text-xs text-on-surface-variant mb-2 data-font uppercase tracking-wider">Valuation</div>
              {[
                { label: 'P/E Ratio', value: metrics.pe_ratio?.toFixed(1) },
                { label: 'P/S Ratio', value: metrics.ps_ratio?.toFixed(1) },
                { label: 'P/B Ratio', value: metrics.pb_ratio?.toFixed(1) },
                { label: 'EV/EBITDA', value: metrics.ev_ebitda?.toFixed(1) },
              ].map((item) => (
                <div key={item.label} className="flex justify-between items-center py-1 border-b border-outline-variant/30">
                  <span className="text-xs text-on-surface-variant">{item.label}</span>
                  <span className="text-sm font-semibold data-font text-on-surface">{item.value || '—'}</span>
                </div>
              ))}
              <div className="text-xs text-on-surface-variant mb-2 mt-4 data-font uppercase tracking-wider">Profitability</div>
              {[
                { label: 'ROE', value: metrics.roe ? `${(metrics.roe * 100).toFixed(1)}%` : '—' },
                { label: 'ROA', value: metrics.roa ? `${(metrics.roa * 100).toFixed(1)}%` : '—' },
                { label: 'Gross Margin', value: metrics.gross_margin ? `${(metrics.gross_margin * 100).toFixed(1)}%` : '—' },
                { label: 'Operating Margin', value: metrics.operating_margin ? `${(metrics.operating_margin * 100).toFixed(1)}%` : '—' },
                { label: 'Net Margin', value: metrics.net_margin ? `${(metrics.net_margin * 100).toFixed(1)}%` : '—' },
              ].map((item) => (
                <div key={item.label} className="flex justify-between items-center py-1 border-b border-outline-variant/30">
                  <span className="text-xs text-on-surface-variant">{item.label}</span>
                  <span className="text-sm font-semibold data-font text-on-surface">{item.value}</span>
                </div>
              ))}
              <div className="text-xs text-on-surface-variant mb-2 mt-4 data-font uppercase tracking-wider">Health & Growth</div>
              {[
                { label: 'Debt/Equity', value: metrics.debt_equity?.toFixed(2) },
                { label: 'FCF Yield', value: metrics.fcf_yield ? `${(metrics.fcf_yield * 100).toFixed(1)}%` : '—' },
                { label: 'Revenue Growth', value: metrics.revenue_growth ? `${(metrics.revenue_growth * 100).toFixed(1)}%` : '—' },
                { label: 'Earnings Growth', value: metrics.earnings_growth ? `${(metrics.earnings_growth * 100).toFixed(1)}%` : '—' },
                { label: 'FCF Growth', value: metrics.fcf_growth ? `${(metrics.fcf_growth * 100).toFixed(1)}%` : '—' },
              ].map((item) => (
                <div key={item.label} className="flex justify-between items-center py-1 border-b border-outline-variant/30">
                  <span className="text-xs text-on-surface-variant">{item.label}</span>
                  <span className="text-sm font-semibold data-font text-on-surface">{item.value}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-8 text-center text-on-surface-variant">
              <span className="material-symbols-outlined text-4xl mb-2 block">calculate</span>
              <p>No metrics available.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}