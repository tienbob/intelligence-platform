import { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { getCompanies, getStockQuote } from '../services/api';

export default function Search() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialQuery = searchParams.get('q') || '';
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState(null);

  async function handleSearch(e) {
    e?.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      // Try stock quote first — this triggers auto-ingestion on the backend
      // if the ticker isn't tracked yet, so searching self-populates the platform.
      const upperQuery = query.trim().toUpperCase();
      try {
        const quote = await getStockQuote(upperQuery);
        setResults({ type: 'stock', data: quote });
      } catch (quoteErr) {
        // Stock quote failed — fall back to company name search
        const companies = await getCompanies({ limit: 100 });
        const filtered = (companies?.companies || []).filter(
          (c) =>
            c.ticker?.toUpperCase().includes(upperQuery) ||
            c.name?.toUpperCase().includes(upperQuery)
        );
        if (filtered.length > 0) {
          setResults({ type: 'companies', data: filtered });
        } else {
          setError(`No company found for "${query}". Try a valid ticker symbol (e.g. AAPL, MSFT, NVDA).`);
        }
      }
    } catch {
      setError('Search unavailable — backend may be offline');
    } finally {
      setSearching(false);
    }
  }

  // Auto-run the search when arriving with ?q=... from the TopNav search bar,
  // and re-run when the URL query changes (e.g. searching again from TopNav
  // while already on the /search page).
  useEffect(() => {
    if (initialQuery.trim()) {
      setQuery(initialQuery);
      handleSearch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Search</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Search markets, tickers, companies, and analysis.
          </p>
        </div>
      </div>

      {/* Search Bar */}
      <form onSubmit={handleSearch} className="card mb-6">
        <div className="relative">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant">
            search
          </span>
          <input
            className="input-field pl-10 text-lg data-font"
            placeholder="Search by ticker (e.g. AAPL) or company name..."
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          <button
            type="submit"
            className="absolute right-2 top-1/2 -translate-y-1/2 btn-primary text-sm py-1 px-3"
            disabled={searching}
          >
            {searching ? 'Searching...' : 'Search'}
          </button>
        </div>
      </form>

      {/* Error */}
      {error && (
        <div className="mb-6 p-4 rounded border bg-error-container/20 border-error-container/50 text-error">
          <p className="text-sm data-font">{error}</p>
        </div>
      )}

      {/* Results */}
      {results && (
        <div>
          {results.type === 'stock' && results.data && (
            <div className="card mb-6">
              <div className="flex items-center gap-4 mb-4">
                <div className="w-12 h-12 bg-surface-container rounded flex items-center justify-center border border-outline-variant">
                  <span className="text-2xl font-bold text-on-surface data-font">
                    {results.data.ticker?.[0]}
                  </span>
                </div>
                <div>
                  <h2 className="text-2xl font-bold text-on-surface">{results.data.name || results.data.ticker}</h2>
                  <span className="text-sm text-on-surface-variant bg-surface-container-high px-2 py-0.5 rounded data-font">
                    {results.data.ticker}
                  </span>
                </div>
                <div className="ml-auto text-right">
                  <div className="text-3xl font-bold text-on-surface data-font">
                    ${results.data.price?.toFixed(2) || '—'}
                  </div>
                  <div
                    className={`text-sm flex items-center justify-end gap-1 data-font ${
                      (results.data.change_percent || 0) >= 0 ? 'text-tertiary' : 'text-error'
                    }`}
                  >
                    <span className="material-symbols-outlined text-sm">
                      {(results.data.change_percent || 0) >= 0 ? 'arrow_upward' : 'arrow_downward'}
                    </span>
                    {results.data.change_percent != null ? `${results.data.change_percent}%` : '—'}
                    {results.data.change != null ? ` (${results.data.change >= 0 ? '+' : ''}${results.data.change})` : ''}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-surface-variant rounded p-3 border border-outline-variant">
                  <p className="text-xs text-on-surface-variant mb-1">Volume</p>
                  <p className="text-lg font-semibold text-on-surface data-font">
                    {results.data.volume?.toLocaleString() || '—'}
                  </p>
                </div>
                <div className="bg-surface-variant rounded p-3 border border-outline-variant">
                  <p className="text-xs text-on-surface-variant mb-1">Last Updated</p>
                  <p className="text-sm text-on-surface data-font">
                    {results.data.timestamp ? new Date(results.data.timestamp).toLocaleString() : '—'}
                  </p>
                </div>
              </div>
              <div className="mt-4 flex gap-2">
                <button
                  className="btn-primary text-sm py-1.5 px-4"
                  onClick={() => navigate(`/companies/${results.data.ticker}`)}
                >
                  View Company
                </button>
                <button
                  className="btn-secondary text-sm py-1.5 px-4"
                  onClick={() => navigate(`/analysis`)}
                >
                  Run Analysis
                </button>
              </div>
            </div>
          )}

          {results.type === 'companies' && (
            <div className="card overflow-hidden !p-0">
              <div className="p-widget-padding border-b border-outline-variant bg-surface-container-low">
                <h3 className="text-lg font-semibold text-on-surface">
                  Companies ({results.data.length} results)
                </h3>
              </div>
              {results.data.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-surface-container-highest border-b border-outline-variant">
                        <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Ticker</th>
                        <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Name</th>
                        <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Exchange</th>
                        <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Sector</th>
                        <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold text-right">Market Cap</th>
                      </tr>
                    </thead>
                    <tbody className="text-sm data-font text-on-surface">
                      {results.data.map((c, i) => (
                        <tr
                          key={c.id}
                          className={`${
                            i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'
                          } border-b border-outline-variant hover:bg-surface-variant transition-colors cursor-pointer`}
                          onClick={() => navigate(`/companies/${c.ticker}`)}
                        >
                          <td className="py-2 px-4 font-bold">{c.ticker}</td>
                          <td className="py-2 px-4">{c.name}</td>
                          <td className="py-2 px-4 text-on-surface-variant">{c.exchange}</td>
                          <td className="py-2 px-4">{c.sector}</td>
                          <td className="py-2 px-4 text-right">
                            {c.market_cap ? `$${(c.market_cap / 1e9).toFixed(1)}B` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="py-12 text-center text-on-surface-variant">
                  <span className="material-symbols-outlined text-4xl mb-2 block">search_off</span>
                  <p>No companies found matching "{query}".</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Empty State */}
      {!results && !searching && !error && (
        <div className="card py-16 text-center text-on-surface-variant">
          <span className="material-symbols-outlined text-6xl mb-4 block">search</span>
          <p className="text-lg mb-2">Search for companies and market data</p>
          <p className="text-sm">Enter a ticker symbol (e.g. AAPL, MSFT) or company name above.</p>
        </div>
      )}
    </div>
  );
}