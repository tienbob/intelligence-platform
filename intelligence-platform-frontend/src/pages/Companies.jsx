import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getCompanies } from '../services/api';
import StatusChip from '../components/StatusChip';

export default function Companies() {
  const navigate = useNavigate();
  const [companies, setCompanies] = useState([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const data = await getCompanies({ limit: 100 });
        setCompanies(data?.companies || []);
      } catch {
        // API not available
      }
    }
    load();
  }, []);

  const filtered = companies.filter((c) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      (c.ticker || '').toLowerCase().includes(q) ||
      (c.name || '').toLowerCase().includes(q) ||
      (c.sector || '').toLowerCase().includes(q) ||
      (c.industry || '').toLowerCase().includes(q)
    );
  });

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
              placeholder="Search companies..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>
      </div>

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
                    onClick={() => navigate(`/companies/${c.ticker}`)}
                    className={`${
                      i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'
                    } border-b border-outline-variant hover:bg-surface-variant transition-colors group cursor-pointer`}
                  >
                    <td className="py-2 px-4 font-bold">{c.ticker}</td>
                    <td className="py-2 px-4">{c.name}</td>
                    <td className="py-2 px-4 text-on-surface-variant">{c.exchange}</td>
                    <td className="py-2 px-4">{c.sector}</td>
                    <td className="py-2 px-4 text-on-surface-variant">{c.industry}</td>
                    <td className="py-2 px-4 text-right">
                      {c.market_cap ? `$${(c.market_cap / 1e9).toFixed(1)}B` : '—'}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-on-surface-variant">
                    <span className="material-symbols-outlined text-4xl mb-2 block">business</span>
                    <p>No companies tracked yet. Start by ingesting market data.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}