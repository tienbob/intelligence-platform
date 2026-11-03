export default function Documentation() {
  return (
    <div className="max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-on-surface flex items-center gap-3 mb-2">
        <span aria-hidden="true" className="material-symbols-outlined text-secondary text-3xl">description</span>
        Documentation
      </h1>
      <p className="text-sm text-on-surface-variant mb-8">
        How our scores and AI analysis work, in plain English.
      </p>

      {/* ── TickerRadar presentation ──────────────────────────────── */}
      <section className="card p-4 mb-6">
        <h2 className="sr-only">TickerRadar presentation</h2>
        {/* Same-origin <iframe>, not <object>: the app CSP sets object-src
            'none' (blocks <object>/<embed>), while frame-src falls back to
            default-src 'self' and allows same-origin iframes. Framing the PDF
            itself is permitted by the dedicated nginx location for it
            (X-Frame-Options SAMEORIGIN + frame-ancestors 'self'). */}
        <iframe
          src="/tickerradar-presentation.pdf#view=FitH"
          title="TickerRadar documentation presentation"
          aria-label="TickerRadar documentation presentation"
          className="w-full h-[80vh] min-h-[600px] rounded border-0"
        />
        <p className="text-xs text-on-surface-variant mt-3 flex items-center gap-1.5 flex-wrap">
          <span aria-hidden="true" className="material-symbols-outlined text-base">download</span>
          <span>
            Can't view the presentation inline?{' '}
            <a
              href="/tickerradar-presentation.pdf"
              download
              className="text-secondary hover:text-secondary/80 underline transition-colors duration-150"
            >
              Download the PDF
            </a>
            .
          </span>
        </p>
      </section>
    </div>
  );
}
