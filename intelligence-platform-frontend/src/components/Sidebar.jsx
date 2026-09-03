import { NavLink, useLocation } from 'react-router-dom';
import { useToast } from './Toast';

const navItems = [
  { to: '/dashboard', label: 'Dashboard', icon: 'dashboard' },
  { to: '/market', label: 'Markets', icon: 'analytics' },
  { to: '/companies', label: 'Companies', icon: 'business' },
  { to: '/search', label: 'Search', icon: 'search' },
  { to: '/portfolio', label: 'Investment Intelligence', icon: 'account_balance_wallet' },
  { to: '/analysis', label: 'AI Jobs', icon: 'memory' },
  { to: '/backtest', label: 'Backtest', icon: 'history' },
  { to: '/alerts', label: 'Alerts', icon: 'notification_important' },
];

export default function Sidebar() {
  const location = useLocation();
  const toast = useToast();

  return (
    <aside className="hidden md:flex fixed left-0 top-0 h-full flex-col pt-16 z-40 bg-surface-container-lowest border-r border-outline-variant w-sidebar-width">
      {/* Sidebar Header */}
      <div className="px-container-margin py-6 border-b border-outline-variant/50 flex items-center gap-3">
        <div className="w-12 h-10 rounded bg-surface-variant border border-outline-variant flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined text-on-surface-variant">account_balance</span>
        </div>
        <div>
          <h2 className="text-sm font-semibold text-on-surface leading-tight">Market Intelligence</h2>
          <p className="text-xs text-on-surface-variant">AI-Powered Research</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 flex flex-col gap-1">
        {navItems.map(({ to, label, icon }) => {
          const isActive = to === '/dashboard' ? location.pathname === '/dashboard' : location.pathname.startsWith(to);
          return (
            <NavLink
              key={to}
              to={to}
              end={to === '/dashboard'}
              className={`group flex items-center gap-3 px-4 py-3 cursor-pointer font-medium text-sm transition-all duration-200 mx-2 rounded ${
                isActive
                  ? 'text-primary font-bold bg-surface-container-high border-l-4 border-secondary-container'
                  : 'text-on-surface-variant hover:bg-surface-variant hover:text-on-surface'
              }`}
            >
              <span
                className="material-symbols-outlined"
                style={isActive ? { fontVariationSettings: "'FILL' 1" } : undefined}
              >
                {icon}
              </span>
              <span>{label}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Sidebar Footer */}
      <div className="px-4 mt-auto">
        <button
          className="w-full py-2 bg-secondary-container text-on-secondary-container text-sm font-semibold rounded hover:opacity-90 transition-opacity mb-4 flex items-center justify-center gap-2"
          onClick={() => toast('Upgrade feature coming soon', 'info')}
        >
          <span className="material-symbols-outlined text-lg">upgrade</span>
          Upgrade Analytics
        </button>
        <div className="border-t border-outline-variant/50 pt-4 flex flex-col gap-2">
          <button
            className="flex items-center gap-3 text-on-surface-variant text-xs hover:text-on-surface transition-colors px-2 cursor-pointer bg-transparent border-none"
            onClick={() => toast('Support feature coming soon', 'info')}
          >
            <span className="material-symbols-outlined text-base">help</span> Support
          </button>
          <button
            className="flex items-center gap-3 text-on-surface-variant text-xs hover:text-on-surface transition-colors px-2 cursor-pointer bg-transparent border-none"
            onClick={() => toast('Documentation feature coming soon', 'info')}
          >
            <span className="material-symbols-outlined text-base">description</span> Documentation
          </button>
        </div>
      </div>
    </aside>
  );
}