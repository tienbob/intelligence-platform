import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../services/auth';
import { useToast } from '../components/Toast';

export default function Register() {
  const navigate = useNavigate();
  const toast = useToast();
  const { register } = useAuth();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    if (!name.trim() || !email.trim() || !password) return;
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    setSubmitting(true);
    try {
      await register(name, email, password);
      toast('Account created successfully', 'success');
      navigate('/');
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
          <span className="material-symbols-outlined text-5xl text-primary mb-2">person_add</span>
          <h1 className="text-2xl font-bold text-on-surface">Create Account</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Join Market Intelligence today
          </p>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded border bg-error-container/20 border-error-container/50 text-error text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Full Name</label>
            <input
              className="input-field"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="John Doe"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Email</label>
            <input
              className="input-field"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Password</label>
            <input
              className="input-field"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min. 8 characters"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-on-surface-variant mb-1 data-font uppercase">Confirm Password</label>
            <input
              className="input-field"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter password"
              required
            />
          </div>
          <button
            type="submit"
            className="btn-primary w-full"
            disabled={submitting}
          >
            {submitting ? 'Creating account...' : 'Create Account'}
          </button>
        </form>

        <p className="text-sm text-on-surface-variant text-center mt-4">
          Already have an account?{' '}
          <Link to="/login" className="text-primary hover:underline font-semibold">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}