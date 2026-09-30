import { useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../services/auth';

// Bottom navigation for small screens. The desktop Sidebar and TopNav are
// both `hidden md:flex`, so without this bar protected pages have no
// navigation below the md breakpoint.
const navItems = [
  { to: '/dashboard', label: 'Home', icon: 'dashboard' },
  { to: '/market', label: 'Markets', icon: 'analytics' },
  { to: '/opportunities', label: 'Opps', icon: 'insights' },
  { to: '/analysis', label: 'AI', icon: 'memory' },
  { to: '/alerts', label: 'Alerts', icon: 'notification_important' },
];

// Every remaining route reachable from the desktop sidebar. Without this the
// rest of the app (and sign-out) was unreachable at narrow widths — audit U02.
const moreItems = [
  { to: '/companies', label: 'Companies', icon: 'business' },
  { to: '/search', label: 'Search', icon: 'search' },
  { to: '/news', label: 'News', icon: 'newspaper' },
  { to: '/events', label: 'Events', icon: 'event' },
  { to: '/backtest', label: 'Backtest', icon: 'history' },
];

export default function MobileNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [moreOpen, setMoreOpen] = useState(false);

  const itemClass = (isActive) =>
    `flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition-colors ${
      isActive ? 'text-secondary' : 'text-on-surface-variant hover:text-on-surface'
    }`;

  return (
    <>
      <nav
        aria-label="Primary"
        className="md:hidden fixed bottom-0 inset-x-0 z-40 bg-surface-container-low border-t border-outline-variant flex pb-[env(safe-area-inset-bottom)]"
      >
        {navItems.map(({ to, label, icon }) => {
          const isActive = to === '/dashboard'
            ? location.pathname === '/dashboard'
            : location.pathname.startsWith(to);
          return (
            <NavLink key={to} to={to} className={itemClass(isActive)}>
              <span
                className="material-symbols-outlined text-xl"
                style={isActive ? { fontVariationSettings: "'FILL' 1" } : undefined}
              >
                {icon}
              </span>
              <span>{label}</span>
            </NavLink>
          );
        })}
        <button
          type="button"
          className={itemClass(moreOpen)}
          aria-haspopup="menu"
          aria-expanded={moreOpen}
          onClick={() => setMoreOpen((value) => !value)}
        >
          <span className="material-symbols-outlined text-xl">more_horiz</span>
          <span>More</span>
        </button>
      </nav>

      {moreOpen && (
        <div className="md:hidden fixed inset-0 z-50 bg-black/50" onClick={() => setMoreOpen(false)}>
          <nav
            aria-label="More navigation"
            className="absolute bottom-0 inset-x-0 bg-surface-container-low border-t border-outline-variant rounded-t-xl p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="grid grid-cols-3 gap-2">
              {moreItems.map(({ to, label, icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  onClick={() => setMoreOpen(false)}
                  className="flex flex-col items-center gap-1 p-3 rounded bg-surface-variant border border-outline-variant text-xs text-on-surface"
                >
                  <span className="material-symbols-outlined">{icon}</span>
                  {label}
                </NavLink>
              ))}
            </div>
            <button
              type="button"
              className="mt-3 w-full py-2 rounded border border-error/40 text-error text-sm font-semibold"
              onClick={() => { setMoreOpen(false); logout(); navigate('/'); }}
            >
              Sign Out
            </button>
          </nav>
        </div>
      )}
    </>
  );
}
