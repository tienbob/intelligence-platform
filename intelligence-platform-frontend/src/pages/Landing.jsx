import { Link } from 'react-router-dom';

export default function Landing() {
  return (
    <div className="min-h-screen bg-background">
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-primary-container/30 via-background to-secondary-container/20" />
        <div className="relative max-w-6xl mx-auto px-6 py-24 text-center">
          <div className="inline-flex items-center gap-2 mb-6 px-4 py-1.5 rounded-full bg-primary-container/60 border border-primary/30 text-primary text-sm font-medium">
            <span className="material-symbols-outlined text-base">insights</span>
            AI-Powered Market Research & Investment Intelligence
          </div>
          <h1 className="text-4xl md:text-6xl font-bold text-on-surface tracking-tight mb-6">
            Make Smarter Investment Decisions
          </h1>
          <p className="text-lg md:text-xl text-on-surface-variant max-w-2xl mx-auto mb-10">
            Real-time market data, fundamental analysis, AI research, risk scoring,
            and strategy backtesting — all in one intelligent platform.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <Link to="/register" className="btn-primary text-base px-6 py-3">Get Started Free</Link>
            <Link to="/login" className="btn-secondary text-base px-6 py-3">Sign In</Link>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-6xl mx-auto px-6 py-16">
        <h2 className="text-2xl md:text-3xl font-bold text-on-surface text-center mb-12">
          Everything You Need to Understand the Market
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            { icon: 'monitoring', title: 'Market Intelligence', desc: 'Track stocks, indices, news, events, and market movements in real time.' },
            { icon: 'psychology_alt', title: 'AI Research & Scoring', desc: 'LLM-powered analysis with evidence-backed investment scores and risk ratings.' },
            { icon: 'history', title: 'Backtesting & Screening', desc: 'Backtest strategies against point-in-time snapshots and screen AI-scored opportunities.' },
          ].map((f) => (
            <div key={f.title} className="card p-6 text-center hover:shadow-lg transition-shadow">
              <span className="material-symbols-outlined text-4xl text-primary mb-3">{f.icon}</span>
              <h3 className="text-lg font-semibold text-on-surface mb-2">{f.title}</h3>
              <p className="text-sm text-on-surface-variant">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-6xl mx-auto px-6 py-16 text-center">
        <div className="card p-10 bg-primary-container/20 border-primary/20">
          <h2 className="text-2xl md:text-3xl font-bold text-on-surface mb-4">Ready to see your dashboard?</h2>
          <p className="text-on-surface-variant mb-8 max-w-xl mx-auto">
            Sign in to access your market dashboard, opportunities, backtests, and alerts.
          </p>
          <Link to="/login" className="btn-primary px-6 py-3">Sign In to Dashboard</Link>
        </div>
      </section>
    </div>
  );
}