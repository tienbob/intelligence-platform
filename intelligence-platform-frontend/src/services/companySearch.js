// Returning false stops startPolling once results or a definitive error arrive.
export function createCompanySearch(term, { getCompanies, getStockQuote, update }) {
  let importing = false;
  return async (active) => {
    try {
      const companies = await getCompanies({ q: term, limit: 100 });
      if (!active()) return false;
      if (companies?.companies?.length) {
        update({ results: { type: 'companies', data: companies.companies } });
        return false;
      }
      if (!/^[A-Za-z0-9.^-]{1,12}$/.test(term)) {
        update({ error: `No company found for "${term}".` });
        return false;
      }
      const quote = await getStockQuote(term.toUpperCase());
      if (active()) update({ results: { type: 'stock', data: quote } });
      return false;
    } catch (error) {
      if (!active()) return false;
      if (error.status === 409 && /^Import failed for /i.test(error.message)) {
        update({ error: error.message });
        return false;
      }
      if (error.status === 404 && /ingestion has started/i.test(error.message)) {
        importing = true;
      } else if (!importing || (error.status >= 400 && error.status < 500)) {
        update({ error: 'Search could not be completed. Try again or check the ticker.' });
        return false;
      }
      // A temporary network/gateway failure must not strand a running import.
      update({ importing: true });
      return true;
    }
  };
}
