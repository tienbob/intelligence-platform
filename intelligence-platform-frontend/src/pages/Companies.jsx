import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getCompanies } from '../services/api';
import Pagination from '../components/Pagination';

export default function Companies() {
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [retry, setRetry] = useState(0);
  const [companies, setCompanies] = useState([]);
  const [search, setSearch] = useState('');
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const data = await getCompanies({ limit: 51, offset: page * 50, q: search.trim() });
        if (!active) return;
        setCompanies((data?.companies || []).slice(0, 50));
        setHasMore((data?.companies || []).length > 50);
        setError(null);
      } catch (error) {
        if (active) { setCompanies([]); setHasMore(false); setError(error.message); }
      } finally { if (active) setLoading(false); }
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [page, search, retry]);
  const filtered = loading ? [] : companies;

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h1 className="text-4xl font-bold text-on-surface">Companies</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Tracked companies and their fundamentals.
          </p>
        </div>
        <div className="flex gap-2">
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-sm">
              search
            </span>
            <input
              className="input-field pl-9 w-56 data-font"
              placeholder="Company name or ticker..."
              aria-label="Company name or ticker"
              maxLength={100}
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            />
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-6 p-4 rounded-lg border border-error/30 bg-error/5 text-sm text-error flex flex-wrap items-center justify-between gap-2">
          <p>Could not load companies: {error}</p>
          <button className="btn-secondary btn-sm" onClick={() => setRetry(value => value + 1)}>Retry</button>
        </div>
      )}

      <div className="card overflow-hidden !p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-highest border-b border-outline-variant">
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Ticker</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Name</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Exchange</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Sector</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold">Industry</th>
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold text-right">Market Cap</th>
              </tr>
            </thead>
            <tbody className="text-sm data-font text-on-surface">
              {filtered.length > 0 ? (
                filtered.map((c, i) => (
                  <tr
                    key={c.id}
                    className={`${
                      i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'
                    } border-b border-outline-variant hover:bg-surface-variant transition-colors group cursor-pointer`}
                  >
                    <td className="py-2 px-4 font-bold"><Link className="underline" to={`/companies/${encodeURIComponent(c.ticker)}`}>{c.ticker}</Link></td>
                    <td className="py-2 px-4">{c.name}</td>
                    <td className="py-2 px-4 text-on-surface-variant">{c.exchange}</td>
                    <td className="py-2 px-4">{c.sector}</td>
                    <td className="py-2 px-4 text-on-surface-variant">{c.industry}</td>
                    <td className="py-2 px-4 text-right">
                      {c.market_cap ? `$${(c.market_cap / 1e9).toFixed(1)}B` : '—'}
                    </td>
                  </tr>
                ))
              ) : !error ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-on-surface-variant">
                    <span className="material-symbols-outlined text-4xl mb-2 block">business</span>
                    <p>{loading ? 'Loading companies…' : 'No companies found on this page.'}</p>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <Pagination
          label="Company pages"
          page={page}
          hasMore={hasMore}
          loading={loading}
          onPrev={() => setPage((p) => p - 1)}
          onNext={() => setPage((p) => p + 1)}
        />
      </div>
    </div>
  );
}