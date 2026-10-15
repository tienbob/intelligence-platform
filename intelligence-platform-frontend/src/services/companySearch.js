// Returning false stops startPolling once results or a definitive error arrive.
export function createCompanySearch(term, { getCompanies, getCompany, getStockQuote, update, now = Date.now }) {
  let importing = false;
  let importStartedAt;
  return async (active) => {
    try {
      // A request must finish or abort so it cannot block every future poll.
      const options = { cache: 'no-store', signal: AbortSignal.timeout(15000) };
      if (importing) {
        // The direct company endpoint reads the persisted record even when
        // later price/provider work is incomplete. Do not wait for a quote.
        const company = await getCompany(term.toUpperCase(), options);
        if (active()) update({ results: { type: 'companies', data: [company] } });
        return false;
      }
      const companies = await getCompanies({ q: term, limit: 100 }, options);
      if (!active()) return false;
      if (companies?.companies?.length) {
        update({ results: { type: 'companies', data: companies.companies } });
        return false;
      }
      if (!/^[A-Za-z0-9.^-]{1,12}$/.test(term)) {
        update({ error: `No company found for "${term}".` });
        return false;
      }
      const quote = await getStockQuote(term.toUpperCase(), options);
      if (active()) update({ results: { type: 'stock', data: quote } });
      return false;
    } catch (error) {
      if (!active()) return false;
      if (error.status === 409 && /^Import failed for /i.test(error.message)) {
        update({ error: error.message });
        return false;
      }
      if (error.status === 404 && /ingestion has started/i.test(error.message)) {
        if (!importing) importStartedAt = now();
        importing = true;
      } else if (!importing || (error.status >= 400 && error.status < 500)) {
        update({ error: 'Search could not be completed. Try again or check the ticker.' });
        return false;
      }
      if (now() - importStartedAt >= 5 * 60 * 1000) {
        update({ error: `We couldn’t confirm that ${term.toUpperCase()} is ready. Search again to check its latest status.` });
        return false;
      }
      // A temporary network/gateway failure must not strand a running import.
      update({ importing: true });
      return true;
    }
  };
}
