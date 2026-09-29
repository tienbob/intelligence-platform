import { NavLink, useLocation } from 'react-router-dom';

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

export default function MobileNav() {
  const location = useLocation();

  return (
    <nav
      aria-label="Primary"
      className="md:hidden fixed bottom-0 inset-x-0 z-50 bg-surface-container-low border-t border-outline-variant flex"
    >
      {navItems.map(({ to, label, icon }) => {
        const isActive = to === '/dashboard'
          ? location.pathname === '/dashboard'
          : location.pathname.startsWith(to);
        return (
          <NavLink
            key={to}
            to={to}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition-colors ${
              isActive
                ? 'text-secondary'
                : 'text-on-surface-variant hover:text-on-surface'
            }`}
          >
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
    </nav>
  );
}
