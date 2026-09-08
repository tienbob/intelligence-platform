import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getCompanies, deleteCompany } from '../services/api';
import { useToast } from '../components/Toast';

export default function Companies() {
  const navigate = useNavigate();
  const toast = useToast();
  const [companies, setCompanies] = useState([]);
  const [search, setSearch] = useState('');
  const [showNonStock, setShowNonStock] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const loadCompanies = useCallback(async () => {
    try {
      const data = await getCompanies({ limit: 100 });
      setCompanies(data?.companies || []);
    } catch {
      // API not available
    }
  }, []);

  useEffect(() => {
    loadCompanies();
  }, [loadCompanies]);

  const filtered = companies.filter((c) => {
    // Instrument-type gate first, independent of the search term.
    if (!showNonStock && c.instrument_type !== 'common_stock') return false;
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      (c.ticker || '').toLowerCase().includes(q) ||
      (c.name || '').toLowerCase().includes(q) ||
      (c.sector || '').toLowerCase().includes(q) ||
      (c.industry || '').toLowerCase().includes(q)
    );
  });

  function confirmDelete(company) {
    setPendingDelete(company);
  }

  function cancelDelete() {
    setPendingDelete(null);
  }

  async function executeDelete() {
    if (!pendingDelete) return;
    const ticker = pendingDelete.ticker;
    setPendingDelete(null);
    try {
      await deleteCompany(ticker);
      toast(`${ticker} deleted`, 'success');
      await loadCompanies();
    } catch (err) {
      toast(err.message || `Failed to delete ${ticker}`, 'error');
    }
  }

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
          <label className="flex items-center gap-2 text-sm text-on-surface-variant cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showNonStock}
              onChange={(e) => setShowNonStock(e.target.checked)}
              className="accent-secondary-container"
            />
            Show non-stock instruments
          </label>
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
                <th className="py-2 px-4 text-xs text-on-surface-variant font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm data-font text-on-surface">
              {filtered.length > 0 ? (
                filtered.map((c, i) => (
                  <tr
                    key={c.id}
                    className={`${
                      i % 2 === 0 ? 'bg-surface' : 'bg-surface-dim'
                    } border-b border-outline-variant hover:bg-surface-variant transition-colors group`}
                  >
                    <td
                      className="py-2 px-4 font-bold cursor-pointer"
                      onClick={() => navigate(`/companies/${c.ticker}`)}
                    >
                      <span className="inline-flex items-center gap-1.5">
                        {c.ticker}
                        {c.instrument_type && c.instrument_type !== 'common_stock' && (
                          <span
                            className={`text-[10px] px-1.5 py-0.5 rounded font-sans font-medium uppercase tracking-wide ${
                              c.instrument_type === 'unknown'
                                ? 'bg-surface-variant text-on-surface-variant'
                                : 'bg-secondary-container/20 text-secondary-fixed border border-secondary-container/40'
                            }`}
                          >
                            {c.instrument_type === 'unknown' ? 'unclassified' : c.instrument_type.replace('_', ' ')}
                          </span>
                        )}
                      </span>
                    </td>
                    <td
                      className="py-2 px-4 cursor-pointer"
                      onClick={() => navigate(`/companies/${c.ticker}`)}
                    >
                      {c.name}
                    </td>
                    <td
                      className="py-2 px-4 text-on-surface-variant cursor-pointer"
                      onClick={() => navigate(`/companies/${c.ticker}`)}
                    >
                      {c.exchange}
                    </td>
                    <td
                      className="py-2 px-4 cursor-pointer"
                      onClick={() => navigate(`/companies/${c.ticker}`)}
                    >
                      {c.sector}
                    </td>
                    <td
                      className="py-2 px-4 text-on-surface-variant cursor-pointer"
                      onClick={() => navigate(`/companies/${c.ticker}`)}
                    >
                      {c.industry}
                    </td>
                    <td
                      className="py-2 px-4 text-right cursor-pointer"
                      onClick={() => navigate(`/companies/${c.ticker}`)}
                    >
                      {c.market_cap ? `$${(c.market_cap / 1e9).toFixed(1)}B` : '—'}
                    </td>
                    <td className="py-2 px-4 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          confirmDelete(c);
                        }}
                        className="p-1.5 rounded hover:bg-error-container/30 text-on-surface-variant hover:text-error transition-colors opacity-0 group-hover:opacity-100"
                        title={`Delete ${c.ticker}`}
                      >
                        <span className="material-symbols-outlined text-[18px]">delete</span>
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-on-surface-variant">
                    <span className="material-symbols-outlined text-4xl mb-2 block">business</span>
                    <p>No companies tracked yet. Start by ingesting market data.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {pendingDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="card max-w-md w-full mx-4 !p-6">
            <div className="flex items-start gap-3 mb-4">
              <span className="material-symbols-outlined text-error text-2xl">warning</span>
              <div>
                <h3 className="text-lg font-semibold text-on-surface">
                  Delete {pendingDelete.ticker}?
                </h3>
                <p className="text-sm text-on-surface-variant mt-1">
                  This will permanently remove <strong>{pendingDelete.name}</strong> and all
                  of its analysis records. This action cannot be undone.
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button onClick={cancelDelete} className="btn-secondary btn-sm">
                Cancel
              </button>
              <button
                onClick={executeDelete}
                className="btn-sm px-4 py-2 rounded font-semibold bg-error-container text-on-error-container hover:opacity-90 transition-opacity"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}