import { getStoredRefreshToken, storeTokens } from './token';

// Single-flight access-token refresh: when several requests hit 401 at the
// same moment, they share one /auth/refresh call instead of racing each
// other (which can burn the refresh token).
let inFlight = null;

/**
 * Attempt a silent token refresh.
 * @returns {Promise<string|null>} the new access token, or null on failure.
 */
export async function refreshAccessToken() {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) {
    return null;
  }
  if (!inFlight) {
    inFlight = (async () => {
      try {
        const res = await fetch('/api/v1/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) {
          return null;
        }
        const json = await res.json();
        const data = json?.data || json;
        if (!data?.access_token) {
          return null;
        }
        storeTokens(data.access_token, data.refresh_token);
        return data.access_token;
      } catch {
        return null;
      } finally {
        inFlight = null;
      }
    })();
  }
  return inFlight;
}
