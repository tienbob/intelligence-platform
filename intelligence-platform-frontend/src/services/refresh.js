import { getStoredRefreshToken, getSessionGeneration, storeTokens } from './token.js';

let inFlight = null;
export async function refreshAccessToken() {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) return null;
  const generation = getSessionGeneration();
  if (inFlight?.key === refreshToken && inFlight.generation === generation) return inFlight.promise;
  const flight = { key: refreshToken, generation };
  flight.promise = (async () => {
    try {
      const res = await fetch('/api/v1/auth/refresh', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return null;
      const json = await res.json();
      const data = json?.data || json;
      // Storage comparison also covers logout/account changes in another tab.
      if (!data?.access_token || generation !== getSessionGeneration() || getStoredRefreshToken() !== refreshToken) return null;
      storeTokens(data.access_token, data.refresh_token);
      return data.access_token;
    } catch { return null; }
    finally { if (inFlight === flight) inFlight = null; }
  })();
  inFlight = flight;
  return flight.promise;
}
