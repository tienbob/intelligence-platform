import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../services/auth';
import { useToast } from '../components/Toast';

export default function Landing() {
  const navigate = useNavigate();
  const toast = useToast();
  const { user, isAuthenticated, loading, logout } = useAuth();
  const firstName = user?.name?.trim().split(/\s+/)[0];

  // Sign out from the home screen: clearTokens() dispatches the session
  // event, so the header and hero switch to the guest view immediately.
  function handleSignOut() {
    logout();
    navigate('/');
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Top bar: adapts to login status so a signed-in user never sees
          "Sign In" calls-to-action on the home screen. Sticky + blurred so
          navigation stays reachable while scrolling. */}
      <header className="sticky top-0 z-40 w-full px-6 py-3.5 flex justify-between items-center bg-surface-container-lowest/80 backdrop-blur border-b border-outline-variant/40">
        <span className="text-2xl font-bold text-primary tracking-tight">TickerRadar</span>
        <div className="flex items-center gap-2">
          {loading ? (
            <span role="status" className="text-sm text-on-surface-variant">Checking session…</span>
          ) : isAuthenticated ? (
            <>
              <span className="text-sm text-on-surface-variant hidden sm:block">
                Hi{firstName ? `, ${firstName}` : ''}
              </span>
              <Link to="/dashboard" className="btn-primary text-sm py-1 px-3">Go to Dashboard</Link>
              <button className="btn-secondary text-sm py-1 px-3" onClick={handleSignOut}>
                Sign Out
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="btn-secondary text-sm py-1 px-3">Sign In</Link>
              <Link to="/register" className="btn-primary text-sm py-1 px-3">Register</Link>
            </>
          )}
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-primary-container/30 via-background to-secondary-container/20" />
        <div className="relative max-w-6xl mx-auto px-6 py-16 md:py-24 text-center">
          <div className="inline-flex items-center gap-2 mb-6 px-4 py-1.5 rounded-full bg-primary-container/60 border border-primary/30 text-primary text-sm font-medium">
            <span className="material-symbols-outlined text-base">
              {isAuthenticated ? 'waving_hand' : 'insights'}
            </span>
            {isAuthenticated
              ? 'You are signed in — your workspace is ready'
              : 'AI-Powered Market Research & Investment Intelligence'}
          </div>
          <h1 className="text-4xl md:text-6xl font-bold text-on-surface tracking-tight mb-6">
            {isAuthenticated ? `Welcome back${firstName ? `, ${firstName}` : ''}` : 'Make Smarter Investment Decisions'}
          </h1>
          <p className="text-lg md:text-xl text-on-surface-variant max-w-2xl mx-auto mb-8">
            {isAuthenticated
              ? 'Jump straight back into your dashboard, AI-scored opportunities, backtests and alerts.'
              : 'Real-time market data, fundamental analysis, AI research, risk scoring, and strategy backtesting — all in one intelligent platform.'}
          </p>
          {/* Quick capability chips: scan what the product offers without
              having to read the three feature cards below. */}
          <div className="flex flex-wrap justify-center gap-2 mb-10">
            {['Live market data', 'AI-driven scoring', 'Strategy backtesting'].map((chip) => (
              <span
                key={chip}
                className="px-3 py-1 rounded-full bg-surface-variant border border-outline-variant text-xs text-on-surface-variant"
              >
                {chip}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap justify-center gap-4">
            {isAuthenticated ? (
              <>
                <Link to="/dashboard" className="btn-primary text-base px-6 py-3">Go to Dashboard</Link>
                <Link to="/opportunities" className="btn-secondary text-base px-6 py-3">View Opportunities</Link>
              </>
            ) : (
              <>
                <Link to="/register" className="btn-primary text-base px-6 py-3">Get Started Free</Link>
                <Link to="/login" className="btn-secondary text-base px-6 py-3">Sign In</Link>
              </>
            )}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-6xl mx-auto px-6 py-16">
        <h2 className="text-2xl md:text-3xl font-bold text-on-surface text-center mb-3">
          Everything You Need to Understand the Market
        </h2>
        <p className="text-on-surface-variant text-center max-w-2xl mx-auto mb-12">
          From raw market data to an explainable recommendation — one workflow, fully transparent.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            { icon: 'monitoring', title: 'Market Tracking', desc: 'Track stocks, indices, news, events, and market movements in real time.' },
            { icon: 'psychology_alt', title: 'AI Research & Scoring', desc: 'LLM-powered analysis with evidence-backed investment scores and risk ratings.' },
            { icon: 'history', title: 'Backtesting & Screening', desc: 'Backtest strategies against point-in-time snapshots and screen AI-scored opportunities.' },
          ].map((f) => (
            <div key={f.title} className="card p-6 text-center hover:shadow-lg hover:-translate-y-1 transition-all duration-200">
              <div className="w-12 h-12 rounded-full bg-primary-container/60 border border-primary/20 flex items-center justify-center mx-auto mb-4">
                <span className="material-symbols-outlined text-2xl text-primary">{f.icon}</span>
              </div>
              <h3 className="text-lg font-semibold text-on-surface mb-2">{f.title}</h3>
              <p className="text-sm text-on-surface-variant">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Help & resources — surfaced mid-page so Support and Documentation
          are easy to reach instead of hiding at the very bottom of the page. */}
      <section className="max-w-6xl mx-auto px-6 pb-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Link
            to="/documentation"
            className="card p-5 flex items-center gap-4 hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200"
          >
            <div className="w-10 h-10 rounded bg-secondary-container/60 border border-outline-variant flex items-center justify-center flex-shrink-0">
              <span className="material-symbols-outlined text-primary">description</span>
            </div>
            <div className="flex-1">
              <h3 className="text-base font-semibold text-on-surface mb-0.5">Documentation</h3>
              <p className="text-sm text-on-surface-variant">
                How our scoring and AI analysis work, in plain English.
              </p>
            </div>
            <span className="material-symbols-outlined text-on-surface-variant" aria-hidden="true">chevron_right</span>
          </Link>
          <button
            type="button"
            className="card p-5 flex items-center gap-4 text-left hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200 cursor-pointer"
            onClick={() => toast('Support feature coming soon', 'info')}
          >
            <div className="w-10 h-10 rounded bg-secondary-container/60 border border-outline-variant flex items-center justify-center flex-shrink-0">
              <span className="material-symbols-outlined text-primary">help</span>
            </div>
            <div className="flex-1">
              <h3 className="text-base font-semibold text-on-surface mb-0.5">Support</h3>
              <p className="text-sm text-on-surface-variant">
                Questions, feedback or trouble with your account — we're here.
              </p>
            </div>
            <span className="material-symbols-outlined text-on-surface-variant" aria-hidden="true">chevron_right</span>
          </button>
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-6xl mx-auto px-6 pt-12 pb-20 text-center">
        <div className="card p-10 bg-primary-container/20 border-primary/20">
          <h2 className="text-2xl md:text-3xl font-bold text-on-surface mb-4">
            {isAuthenticated ? 'Ready to pick up where you left off?' : 'Ready to see your dashboard?'}
          </h2>
          <p className="text-on-surface-variant mb-8 max-w-xl mx-auto">
            {isAuthenticated
              ? 'Your dashboard, opportunities, backtests, and alerts are waiting.'
              : 'Sign in to access your market dashboard, opportunities, backtests, and alerts.'}
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            {isAuthenticated ? (
              <Link to="/dashboard" className="btn-primary px-6 py-3">Go to Dashboard</Link>
            ) : (
              <Link to="/login" className="btn-primary px-6 py-3">Sign In to Dashboard</Link>
            )}
            <Link to="/documentation" className="btn-secondary px-6 py-3">How Our Scoring Works</Link>
          </div>
        </div>
      </section>
    </div>
  );
}