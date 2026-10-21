export default function Documentation() {
  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-on-surface flex items-center gap-3 mb-2">
        <span aria-hidden="true" className="material-symbols-outlined text-secondary text-3xl">description</span>
        Documentation
      </h1>
      <p className="text-sm text-on-surface-variant mb-8">
        How our scores and AI analysis work, in plain English.
      </p>

      {/* ── The three numbers ─────────────────────────────────────── */}
      <section className="card p-6 mb-6">
        <h2 className="text-lg font-semibold text-on-surface mb-4">The three numbers you'll see</h2>
        <ul className="space-y-3 text-sm text-on-surface-variant">
          <li>
            <strong className="text-on-surface">Investment score (0–100)</strong> — a research ranking of how
            attractive a company looks under our rules. Higher = more attractive. It is{' '}
            <em>not a predicted return</em>.
          </li>
          <li>
            <strong className="text-on-surface">Risk score (0–100)</strong> — how much concern we see. Higher =
            more concern. Read it separately from the investment score.
          </li>
          <li>
            <strong className="text-on-surface">Confidence (0–1)</strong> — how much input data backs the
            analysis. Low confidence means inputs were thin or missing, not that the call is wrong.
          </li>
        </ul>
      </section>

      {/* ── Score calculation ─────────────────────────────────────── */}
      <section className="card p-6 mb-6">
        <h2 className="text-lg font-semibold text-on-surface mb-2">How the investment score is calculated</h2>
        <p className="text-sm text-on-surface-variant mb-4">
          The score is a weighted average of seven components, computed by fixed rules (not the AI model),
          with risk subtracted. Weights are configurable defaults shown below.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-outline-variant text-left">
                <th className="py-2 pr-4 text-on-surface font-semibold">Component</th>
                <th className="py-2 pr-4 text-on-surface font-semibold">Weight</th>
                <th className="py-2 text-on-surface font-semibold">What it measures</th>
              </tr>
            </thead>
            <tbody className="text-on-surface-variant">
              {[
                ['Fundamentals', '30%', 'Financial health: revenue, profit margins, debt, cash flow.'],
                ['Valuation', '20%', 'Price vs. earnings and book value — is the stock cheap or expensive?'],
                ['Growth', '15%', 'Revenue and earnings growth trend over time.'],
                ['Technical', '10%', 'Price trends, momentum and chart patterns.'],
                ['Sentiment', '10%', 'Tone of recent news coverage about the company.'],
                ['Catalysts', '10%', 'Recent or upcoming events that could move the price.'],
                ['Risk', '−15%', 'Volatility, leverage and downside risk — subtracted from the total.'],
              ].map(([name, weight, desc]) => (
                <tr key={name} className="border-b border-outline-variant/40 last:border-b-0">
                  <td className="py-2 pr-4 text-on-surface font-medium whitespace-nowrap">{name}</td>
                  <td className="py-2 pr-4 data-font whitespace-nowrap">{weight}</td>
                  <td className="py-2">{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-on-surface-variant mt-4">
          Final score = sum of each component × its weight, minus the risk contribution. From the score we
          derive a recommendation (Buy / Hold / Sell / Neutral).
        </p>
      </section>
      {/* ── Missing data ──────────────────────────────────────────── */}
      <section className="card p-6 mb-6">
        <h2 className="text-lg font-semibold text-on-surface mb-2">What happens when data is missing?</h2>
        <p className="text-sm text-on-surface-variant mb-3">
          A data-quality check weighs each input before scoring. If an input is missing or thin, it is skipped
          and the score falls back to a neutral 50 with lower confidence — we never fill gaps with guesses.
        </p>
        <p className="text-sm text-on-surface-variant">
          Input importance: <strong className="text-on-surface">price 30%</strong>,{' '}
          <strong className="text-on-surface">fundamentals 30%</strong>, technicals 15%, news 15%, events 10%.
        </p>
      </section>

      {/* ── AI analysis pipeline ──────────────────────────────────── */}
      <section className="card p-6 mb-6">
        <h2 className="text-lg font-semibold text-on-surface mb-4">How the AI analysis works</h2>
        <ol className="space-y-3 text-sm text-on-surface-variant list-decimal list-inside">
          <li>
            <strong className="text-on-surface">Collect data</strong> — market prices, fundamentals, news and
            events are ingested for each company.
          </li>
          <li>
            <strong className="text-on-surface">Compute scores</strong> — the deterministic scoring engine
            (Python rules, not the AI) produces the numbers above.
          </li>
          <li>
            <strong className="text-on-surface">Retrieve evidence (RAG)</strong> — relevant news and documents
            are found by semantic similarity so the AI writes from real sources, not memory.
          </li>
          <li>
            <strong className="text-on-surface">Write the analysis</strong> — a large language model drafts the
            thesis, risks and recommendation, citing the retrieved evidence.
          </li>
          <li>
            <strong className="text-on-surface">Verify citations</strong> — every claim must point to a
            registered source; unsupported citations are dropped automatically before you see the analysis.
          </li>
        </ol>
      </section>

      {/* ── Limitations ───────────────────────────────────────────── */}
      <section className="card p-6 bg-error-container/10 border-error-container/30">
        <h2 className="text-lg font-semibold text-on-surface mb-2 flex items-center gap-2">
          <span aria-hidden="true" className="material-symbols-outlined text-error text-xl">info</span>
          Know the limitations
        </h2>
        <ul className="space-y-2 text-sm text-on-surface-variant list-disc list-inside">
          <li>Scores are a research ranking under our rules — not investment advice or a return forecast.</li>
          <li>Scores are point-in-time: market data and scoring rules change, so older scores age.</li>
          <li>AI-written text can contain errors — always check the cited sources before acting.</li>
          <li>Confidence tells you how complete the inputs were, not how likely the call is to be right.</li>
        </ul>
      </section>
    </div>
  );
}
