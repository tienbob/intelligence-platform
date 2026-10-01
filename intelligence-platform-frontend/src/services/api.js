import { getStoredToken, clearTokens } from './token';
import { refreshAccessToken } from './refresh';
import { readJson } from './http';

const BASE_URL = '/api/v1';

// Endpoints that should NOT trigger a session-expired redirect on 401.
// This prevents redirect loops while the user is actively logging in/refreshing.
const AUTH_ROUTES = ['/auth/login', '/auth/register', '/auth/refresh'];

function isAuthRoute(url) {
  return AUTH_ROUTES.some((route) => url.includes(route));
}

async function request(url, options = {}, retried = false) {
  const token = getStoredToken();
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  // Spread options first so a caller-supplied `headers` (e.g. an
  // Idempotency-Key) cannot silently replace the merged Content-Type /
  // Authorization headers (audit Q07).
  const res = await fetch(`${BASE_URL}${url}`, {
    ...options,
    headers,
  });
  // Session expired (401) on a protected endpoint → try one silent token
  // refresh, then retry the request once. Only if the refresh fails do we
  // clear tokens and redirect (avoids redirect loops on auth endpoints).
  if (res.status === 401 && !isAuthRoute(url) && !retried) {
    // A response from an old account must not refresh or clear a newer session.
    if (getStoredToken() !== token) throw new Error('Session changed. Please retry.');
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request(url, options, true);
    }
    if (getStoredToken() === token && !window.location.pathname.startsWith('/login')) {
      clearTokens();
      window.location.href = '/login?expired=1';
    }
  }
  if (!res.ok) {
    // Prefer the error envelope; fall back to plain text/HTML bodies without
    // pretending an HTML error page is JSON.
    const err = await readJson(res).catch(() => null);
    // Architecture §71: error responses use {"error": {"code": ..., "message": ...}}
    // Fall back to flat {"detail": "..."} for backward compatibility
    const message = err?.error?.message || err?.detail
      || `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ''}`;
    throw new Error(message);
  }
  // 204 No Content — no body to parse (e.g. DELETE responses)
  if (res.status === 204) {
    return null;
  }
  const json = await readJson(res);
  // Architecture §71: unwrap response envelope {"data": {...}, "meta": {...}}
  // If the response has a "data" key at the top level, return its value.
  // Otherwise return the raw response (for health/metrics endpoints that skip the envelope).
  if (json && typeof json === 'object' && 'data' in json) {
    return json.data;
  }
  return json;
}

// NOTE (audit Q07): the unused `getHealthLive` / `getHealthReady` / `getMetrics`
// helpers were removed. They prefixed `/api/v1` while Rails serves health at
// the root (`/health/live`, `/health/ready`), and `/metrics` is key-gated and
// deliberately not proxied (audit S02) — so they could only ever have returned
// an HTML 404 page to the client.

// Stocks
export const getStockQuote = (ticker) => request(`/stocks/${ticker}`);
export const getStockPrices = (ticker, params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/stocks/${ticker}/prices${qs ? `?${qs}` : ''}`);
};

// Companies
export const getCompanies = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/companies/${qs ? `?${qs}` : ''}`);
};
export const getCompany = (ticker) => request(`/companies/${ticker}`);

// Prices
export const getPrices = (ticker, params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/prices/${ticker}${qs ? `?${qs}` : ''}`);
};

// Financials
export const getFinancialStatements = (ticker, params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/financials/${ticker}/statements${qs ? `?${qs}` : ''}`);
};
export const getFinancialMetrics = (ticker) => request(`/financials/${ticker}/metrics`);
export const getTechnicalIndicators = (ticker) => request(`/financials/${ticker}/technical`);

// News
export const getNews = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/news/${qs ? `?${qs}` : ''}`);
};
export const getNewsItem = (id) => request(`/news/${id}`);

// Events
export const getEvents = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/events/${qs ? `?${qs}` : ''}`);
};
export const getEvent = (id) => request(`/events/${id}`);

// Market
export const getMarketOverview = () => request('/market/overview');
export const getMarketIndices = () => request('/market/indices');
export const getTopMovers = () => request('/market/top-movers');

// ── Idempotency (audit F04) ──────────────────────────────────────
// A key per create attempt lets the gateway/Python deduplicate a retried
// request instead of queueing a second paid analysis. The merged headers in
// `request()` guarantee the Authorization header survives alongside it.
function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `mi-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// Analysis
export const createCompanyAnalysis = (body) =>
  request('/analysis/company', {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'Idempotency-Key': newIdempotencyKey() },
  });
export const getAnalysis = (id) => request(`/analysis/${id}`);
export const cancelAnalysis = (id) => request(`/analysis/${id}/cancel`, { method: 'POST' });
export const deleteAnalysis = (id) => request(`/analysis/${id}`, { method: 'DELETE' });
export const getAnalysisJobs = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/analysis/jobs${qs ? `?${qs}` : ''}`);
};

// Investments
export const getOpportunities = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/investments/opportunities${qs ? `?${qs}` : ''}`);
};

// Backtest
export const getBacktestRuns = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/backtest/runs${qs ? `?${qs}` : ''}`);
};
export const getBacktestRun = (id) => request(`/backtest/runs/${id}`);
export const getBacktestTrades = (id, params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/backtest/runs/${id}/trades${qs ? `?${qs}` : ''}`);
};
export const createBacktestRun = (body) =>
  request('/backtest/runs', { method: 'POST', body: JSON.stringify(body) });
export const getBacktestSnapshots = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/backtest/snapshots${qs ? `?${qs}` : ''}`);
};
export const createBacktestSnapshot = (body) =>
  request('/backtest/snapshots', { method: 'POST', body: JSON.stringify(body) });

// Alerts
export const getAlerts = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/alerts/${qs ? `?${qs}` : ''}`);
};
export const getAlert = (id) => request(`/alerts/${id}`);
export const createAlert = (body) =>
  request('/alerts/', { method: 'POST', body: JSON.stringify(body) });
export const markAlertRead = (id) => request(`/alerts/${id}/read`, { method: 'POST' });
