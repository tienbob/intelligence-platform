import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

// Route-aware document title (audit U06): every tab previously read the
// same static title, so history/bookmarks/multi-tab users could not tell
// pages apart.
const TITLES = {
  dashboard: 'Dashboard',
  market: 'Markets',
  companies: 'Companies',
  news: 'News',
  events: 'Events',
  analysis: 'AI Analysis',
  opportunities: 'Opportunities',
  portfolio: 'Opportunities',
  backtest: 'Backtesting',
  alerts: 'Alerts',
  search: 'Search',
  login: 'Sign In',
  register: 'Create Account',
};

export default function PageTitle() {
  const { pathname } = useLocation();

  useEffect(() => {
    const segment = pathname.split('/').filter(Boolean)[0] || '';
    const page = TITLES[segment];
    document.title = page
      ? `${page} — Market Intelligence`
      : 'Market Intelligence — AI-Powered Research';
  }, [pathname]);

  return null;
}