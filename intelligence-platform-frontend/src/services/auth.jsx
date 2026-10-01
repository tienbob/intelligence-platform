import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getStoredToken, storeTokens, clearTokens, getStoredUser, storeUser, getSessionGeneration, SESSION_EVENT } from './token';
import { refreshAccessToken } from './refresh';
import { readJson } from './http';
const AuthContext = createContext(null);
export function useAuth() { return useContext(AuthContext); }

async function fetchProfile(token) {
  const res = await fetch('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error('Could not validate your session');
  const json = await readJson(res);
  return json?.data || json;
}
export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => ({ token: getStoredToken(), user: getStoredUser() }));
  const [loading, setLoading] = useState(() => !!getStoredToken());
  const [error, setError] = useState(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const sync = () => setSession({ token: getStoredToken(), user: getStoredUser() });
    window.addEventListener(SESSION_EVENT, sync);
    window.addEventListener('storage', sync);
    return () => { window.removeEventListener(SESSION_EVENT, sync); window.removeEventListener('storage', sync); };
  }, []);
  useEffect(() => {
    let cancelled = false;
    const original = getStoredToken();
    if (!original) return;
    const validate = async () => {
      setLoading(true); setError(null);
      try {
        let token = original;
        let res = await fetch('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } });
        if (res.status === 401) {
          token = await refreshAccessToken();
          if (!token) {
            if (getStoredToken() === original) clearTokens();
            return;
          }
          res = await fetch('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } });
        }
        if (cancelled || getStoredToken() !== token) return;
        if (res.status === 401) { clearTokens(); return; }
        if (!res.ok) throw new Error('Session verification unavailable. Retry when the service is back.');
        const json = await readJson(res);
        if (!cancelled && getStoredToken() === token) storeUser(json?.data || json);
      } catch (e) { if (!cancelled) setError(e.message); }
      finally { if (!cancelled) setLoading(false); }
    };
    validate();
    return () => { cancelled = true; };
  }, [retry]);
  const authenticate = useCallback(async (endpoint, body) => {
    clearTokens();
    const generation = getSessionGeneration();
    setLoading(true); setError(null);
    try {
      const res = await fetch(`/api/v1/auth/${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      // Read the body before inspecting the status: a 502/HTML page must not
      // surface as "Unexpected token '<'" from JSON.parse (it used to).
      const json = await readJson(res).catch(() => null);
      if (!res.ok) throw new Error(json?.detail || json?.error?.message || `Authentication failed (HTTP ${res.status})`);
      if (generation !== getSessionGeneration()) throw new Error('Authentication was cancelled');
      const data = json?.data || json;
      storeTokens(data.access_token, data.refresh_token);
      try {
        const user = await fetchProfile(data.access_token);
        if (getStoredToken() === data.access_token) storeUser(user);
      } catch { /* Valid credentials remain usable; next session validation retries profile. */ }
      return data;
    } finally { setLoading(false); }
  }, []);
  const login = useCallback((email, password) => authenticate('login', { email, password }), [authenticate]);
  const register = useCallback((name, email, password) => authenticate('register', { name, email, password }), [authenticate]);
  const logout = useCallback(() => {
    const token = getStoredToken();
    clearTokens(); setLoading(false); setError(null);
    if (token) fetch('/api/v1/auth/logout', {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }, keepalive: true,
    }).catch(() => { /* Local logout remains effective while offline. */ });
  }, []);
  return <AuthContext.Provider value={{ user: session.user, isAuthenticated: !!session.token, loading, error, retrySession: () => setRetry(v => v + 1), login, register, logout, refreshToken: refreshAccessToken }}>{children}</AuthContext.Provider>;
}
