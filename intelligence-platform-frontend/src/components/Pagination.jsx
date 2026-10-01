// Shared list pager, mirroring the Analysis History table footer: the bar sits
// *inside* the card as a bordered top strip, never detached below it. Buttons
// stay visible-but-faded when disabled so the control never jumps layout, and
// the middle slot states the current page. Lookahead APIs don't know totals,
// so it reads "Page N" (not "Page N of M").
export default function Pagination({ label, page, hasMore, loading, onPrev, onNext }) {
  return (
    <nav aria-label={label} className="flex items-center justify-between gap-3 px-4 py-3 border-t border-outline-variant/60 bg-surface-container-lowest/40 text-xs text-on-surface-variant">
      <button className="btn-secondary btn-sm disabled:opacity-30 disabled:cursor-not-allowed" disabled={loading || page === 0} onClick={onPrev}>Previous</button>
      <span>Page {page + 1}</span>
      <button className="btn-secondary btn-sm disabled:opacity-30 disabled:cursor-not-allowed" disabled={loading || !hasMore} onClick={onNext}>Next</button>
    </nav>
  );
}
