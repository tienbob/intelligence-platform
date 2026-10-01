import { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from '../services/auth';
import { getAlerts } from '../services/api';
import { onAlertsChanged } from '../services/alertsSignal';
import { useToast } from './Toast';

export default function TopNav() {
  const navigate = useNavigate();
  const location = useLocation();
  const triggerRef = useRef(null);
  const toast = useToast();
  const { user, isAuthenticated, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [hasUnread, setHasUnread] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => { setMenuOpen(false); }, [location.key]);

  // Close menu on outside click
  useEffect(() => {
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    }
    function handleKey(e) {
      if (e.key === 'Escape' && menuOpen) {
        setMenuOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('pointerdown', handleClick);
    document.addEventListener('focusin', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('pointerdown', handleClick);
      document.removeEventListener('focusin', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [menuOpen]);

  // Real unread indicator: only show the notification dot when the user
  // actually has unread alerts (instead of a permanent fake dot). Refreshes
  // on auth change and whenever Alerts.jsx reports a mutation (audit F03).
  useEffect(() => {
    let active = true;
    let version = 0;
    setHasUnread(false);
    if (!isAuthenticated) return;
    async function refreshUnread() {
      const requestVersion = ++version;
      try {
        const data = await getAlerts({ unread_only: true, limit: 1 });
        if (active && requestVersion === version) setHasUnread((data?.alerts?.length || 0) > 0);
      } catch {
        if (active && requestVersion === version) setHasUnread(false);
      }
    }
    refreshUnread();
    const unsubscribe = onAlertsChanged(refreshUnread);
    return () => { active = false; unsubscribe(); };
  }, [isAuthenticated, user?.id]);

  return (
    <header className="hidden md:flex justify-between items-center w-full px-container-margin h-16 z-50 bg-surface-container-low border-b border-outline-variant fixed top-0">
      {/* Brand + Search */}
      <div className="flex items-center gap-6">
        <Link
          className="flex items-center gap-2 cursor-pointer"
          to={isAuthenticated ? '/dashboard' : '/'}
        >
          <span className="text-2xl font-bold text-primary tracking-tight">
            Market Intelligence
          </span>
        </Link>
        <div className="relative hidden sm:block w-64 md:w-96">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant pointer-events-none text-sm">
            search
          </span>
          <input
            className="w-full bg-surface-container-high border border-outline-variant rounded py-1.5 pl-9 pr-4 text-sm text-on-surface focus:border-secondary-container focus:ring-1 focus:ring-secondary-container focus:outline-none transition-shadow placeholder-on-surface-variant"
            placeholder="Search companies or tickers..."
            aria-label="Search companies or tickers"
            maxLength={100}
            type="text"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                navigate(`/search?q=${encodeURIComponent(e.target.value)}`);
              }
            }}
          />
        </div>
      </div>

      {/* Trailing Actions */}
      <div className="flex items-center gap-4">
        <button
          aria-label="Notifications"
          className="text-on-surface-variant hover:text-primary transition-colors duration-150 cursor-pointer p-1 relative"
          onClick={() => navigate('/alerts')}
        >
          <span className="material-symbols-outlined">notifications</span>
          {hasUnread && (
            <span className="absolute top-1 right-1 w-2 h-2 bg-error rounded-full border border-surface-container-low" />
          )}
        </button>

        {isAuthenticated ? (
          <div className="relative" ref={menuRef}>
            <button
              className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
              ref={triggerRef}
              aria-label="Account options"
              aria-expanded={menuOpen}
              aria-controls="account-options"
              onClick={() => setMenuOpen(!menuOpen)}
            >
              <div className="w-8 h-8 rounded-full bg-primary-container border border-primary flex items-center justify-center overflow-hidden">
                <span className="text-sm font-bold text-on-primary-container data-font">
                  {user?.name?.charAt(0)?.toUpperCase() || 'U'}
                </span>
              </div>
              <span className="text-sm text-on-surface hidden lg:block">{user?.name || 'User'}</span>
            </button>
            {menuOpen && (
              <div id="account-options" className="absolute right-0 top-full mt-2 w-48 bg-surface-container-high border border-outline-variant rounded shadow-lg z-50">
                <div className="px-4 py-3 border-b border-outline-variant">
                  <p className="text-sm font-semibold text-on-surface">{user?.name}</p>
                  <p className="text-xs text-on-surface-variant">{user?.email}</p>
                </div>
                <button
                  className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-variant transition-colors flex items-center gap-2"
                  onClick={() => { setMenuOpen(false); toast('Profile page coming soon', 'info'); }}
                >
                  <span className="material-symbols-outlined text-sm">person</span>
                  Profile
                </button>
                <button
                  className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-variant transition-colors flex items-center gap-2"
                  onClick={() => { setMenuOpen(false); toast('Settings page coming soon', 'info'); }}
                >
                  <span className="material-symbols-outlined text-sm">settings</span>
                  Settings
                </button>
                <div className="border-t border-outline-variant" />
                <button
                  className="w-full text-left px-4 py-2 text-sm text-error hover:bg-error-container/20 transition-colors flex items-center gap-2"
                  onClick={() => { setMenuOpen(false); logout(); toast('Logged out', 'info'); navigate('/'); }}
                >
                  <span className="material-symbols-outlined text-sm">logout</span>
                  Sign Out
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button
              className="btn-secondary text-sm py-1 px-3"
              onClick={() => navigate('/login')}
            >
              Sign In
            </button>
            <button
              className="btn-primary text-sm py-1 px-3"
              onClick={() => navigate('/register')}
            >
              Register
            </button>
          </div>
        )}
      </div>
    </header>
  );
}