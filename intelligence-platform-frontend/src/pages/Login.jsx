import { useState, useEffect } from 'react';
import { useNavigate, useLocation, useSearchParams, Link } from 'react-router-dom';
import { useAuth } from '../services/auth';
import { useToast } from '../components/Toast';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const { login } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  // Show a friendly note when the API layer redirected here after a session
  // expired (?expired=1), then clear the flag from the URL.
  const [sessionExpired] = useState(() => searchParams.has('expired'));
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (searchParams.has('expired')) {
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      toast('Logged in successfully', 'success');
      // Return the user to the page they were bounced from, if any.
      navigate(location.state?.from || '/dashboard', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center">
      <div className="card w-full max-w-md">
        <div className="text-center mb-6">
          <span className="material-symbols-outlined text-5xl text-primary mb-2">account_balance</span>
          <h1 className="text-2xl font-bold text-on-surface">Sign In</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Access your Market Intelligence dashboard
          </p>
        </div>

        {sessionExpired && (
          <div role="status" className="mb-4 p-3 rounded border border-secondary-container/50 bg-secondary-container/10 text-on-surface text-sm">
            Your session expired — please sign in again.
          </div>
        )}

        {error && (
          <div className="mb-4 p-3 rounded border bg-error-container/20 border-error-container/50 text-error text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="login-email" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Email</label>
            <input
              id="login-email"
              name="email"
              autoComplete="email"
              className="input-field"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="login-password" className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Password</label>
            <input
              id="login-password"
              name="password"
              autoComplete="current-password"
              className="input-field"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>
          <button
            type="submit"
            className="btn-primary w-full"
            disabled={submitting}
          >
            {submitting ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <p className="text-sm text-on-surface-variant text-center mt-4">
          Don't have an account?{' '}
          <Link to="/register" className="text-primary hover:underline font-semibold">
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}