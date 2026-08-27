import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getStoredToken, getStoredRefreshToken, storeTokens, clearTokens, getStoredUser, storeUser } from './token';

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => getStoredUser());
  const [token, setToken] = useState(() => getStoredToken());
  const [loading, setLoading] = useState(false);

  const isAuthenticated = !!token;

  // Try to restore session on mount
  useEffect(() => {
    const storedToken = getStoredToken();
    if (storedToken && !token) {
      fetch('/api/v1/auth/me', {
        headers: { Authorization: `Bearer ${storedToken}` },
      })
        .then((res) => {
          if (res.ok) return res.json();
          throw new Error('Session expired');
        })
        .then((data) => {
          const userData = data?.data || data;
          setUser(userData);
          storeUser(userData);
        })
        .catch(() => {
          // Session restore failed (e.g. 401 expired token) → clear tokens and
          // redirect to login. Fall back to stored user only if we're not on a
          // protected page.
          clearTokens();
          setToken(null);
          setUser(null);
          if (!window.location.pathname.startsWith('/login')) {
            window.location.href = '/login';
          }
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async (email, password) => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = err?.error?.message || err?.detail || 'Login failed';
        throw new Error(msg);
      }
      const json = await res.json();
      const data = json?.data || json;
      storeTokens(data.access_token, data.refresh_token);
      setToken(data.access_token);

      // Try to fetch the user; if it fails, fall back to stored user
      try {
        const meRes = await fetch('/api/v1/auth/me', {
          headers: { Authorization: `Bearer ${data.access_token}` },
        });
        if (meRes.ok) {
          const meJson = await meRes.json();
          const userData = meJson?.data || meJson;
          setUser(userData);
          storeUser(userData);
        } else {
          const storedUser = getStoredUser();
          if (storedUser) setUser(storedUser);
        }
      } catch {
        const storedUser = getStoredUser();
        if (storedUser) setUser(storedUser);
      }
      return data;
    } finally {
      setLoading(false);
    }
  }, []);

  const register = useCallback(async (name, email, password) => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = err?.error?.message || err?.detail || 'Registration failed';
        throw new Error(msg);
      }
      const json = await res.json();
      const data = json?.data || json;
      storeTokens(data.access_token, data.refresh_token);
      setToken(data.access_token);

      // Try to fetch the user; if it fails, fall back to stored user
      try {
        const meRes = await fetch('/api/v1/auth/me', {
          headers: { Authorization: `Bearer ${data.access_token}` },
        });
        if (meRes.ok) {
          const meJson = await meRes.json();
          const userData = meJson?.data || meJson;
          setUser(userData);
          storeUser(userData);
        } else {
          const storedUser = getStoredUser();
          if (storedUser) setUser(storedUser);
        }
      } catch {
        const storedUser = getStoredUser();
        if (storedUser) setUser(storedUser);
      }
      return data;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    clearTokens();
    setToken(null);
    setUser(null);
  }, []);

  const refreshToken = useCallback(async () => {
    const refresh = getStoredRefreshToken();
    if (!refresh) {
      logout();
      return null;
    }
    try {
      const res = await fetch('/api/v1/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!res.ok) {
        logout();
        return null;
      }
      const json = await res.json();
      const data = json?.data || json;
      storeTokens(data.access_token, data.refresh_token);
      setToken(data.access_token);
      return data.access_token;
    } catch {
      logout();
      return null;
    }
  }, [logout]);

  return (
    <AuthContext.Provider
      value={{ user, isAuthenticated, loading, login, register, logout, refreshToken }}
    >
      {children}
    </AuthContext.Provider>
  );
}