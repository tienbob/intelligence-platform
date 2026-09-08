# Plan — Instrument Type Classification on `companies`

> Status: Proposed (revised after architecture review)
> Date: 2026-09-08
> Scope: Distinguish operating companies from ETFs/funds/other ticker-addressable
> instruments without restructuring the entity model.

## Objective

The platform ingests any ticker (AAPL, NVDA, SPY, …) into the same `companies`
table with no discriminator. A user sees the S&P 500 ETF alongside Apple with
identical treatment — including company-style financials and analysis. We need
a minimal-change way to mark an entity's instrument type and to surface it in
the UI, without introducing a second entity model (`instruments`) underneath the
existing price/news/filing/event/analysis/embedding graph.

## Terminology (corrected)

`companies` is really a **tradable/security entity keyed by ticker**. "Common
stock" is an *instrument*, not an "operating company" — the company is the
issuer. Documentation and code comments must use instrument language, not
"company vs. not-company":

| `instrument_type` | Meaning | Example |
|---|---|---|
| `common_stock` | Common equity security | AAPL, NVDA, TSLA |
| `etf` | Exchange-traded fund | SPY, QQQ |
| `mutual_fund` | Mutual fund (open-ended fund) | — |
| `unknown` | Classification unresolved / provider returned no signal | (fallback) |

`index` and `crypto` are **out of scope for this change** — they are not
classifiable from the current provider signal and would be dead enum values.

## Non-goals

- No new `instruments` table, no entity-model split.
- No ETF-specific analytics (holdings, expense ratio, AUM, tracking error,
  flows). This plan only *prevents* ETF rows from flowing through company
  analysis unchanged; it does not build the ETF analytics model.
- No `index`/`crypto` classification.

## Target architecture

```text
FMP profile (get_company_profile)
        ↓
classify_instrument(profile)      ← ONE reusable classifier
        ↓
Company.instrument_type
        ↓
    ┌───────────────┬─────────────────┐
    ↓               ↓                 ↓
  API response   frontend badge   ingestion/analysis guard
  (?type= filter)  + filter        (non-stock boundary)
```

---

## Ordered work plan

### 1. Migration — add `instrument_type` with explicit then removed default

New Alembic migration `0022_instrument_type.py` (revises `0021`):

```python
def upgrade():
    op.add_column(
        "companies",
        sa.Column(
            "instrument_type",
            sa.String(20),
            nullable=False,
            server_default="unknown",   # NOT common_stock
        ),
    )
    op.create_index(
        "ix_companies_instrument_type", "companies", ["instrument_type"]
    )
    # Remove the server default so the DB can never silently paper over a
    # classification failure. Application code must set the type explicitly.
    op.alter_column(
        "companies", "instrument_type", server_default=None
    )
```

Rationale (review item 6): a `server_default="common_stock"` would let a bug in
ingestion silently mislabel an unclassified entity as a stock. Default the
column to `unknown` at DDL time (so existing rows backfill safely), then drop
the server default so *new* rows must carry an explicit type. Existing rows keep
`unknown` until the backfill (step 5) classifies them.

### 2. ORM + API schema

- `app/domains/stock/models/company.py`: add
  `instrument_type: Mapped[str] = mapped_column(String(20), default="unknown", index=True)`.
- `app/domains/stock/schemas/company.py`: add `instrument_type: str = "unknown"`
  to `CompanyResponse` so `GET /companies/` and `GET /companies/{ticker}` expose
  it.
- Optional: `GET /companies/?type=etf|common_stock|...` filter on
  `list_companies()` (nice-to-have; FE can also filter client-side).

### 3. One reusable classifier

New module-level function (place in `normalization/companies.py`, next to
`EntityResolver`):

```python
def classify_instrument(profile: dict[str, Any] | None) -> str:
    """
    Map a provider profile to a canonical instrument_type.

    Returns 'unknown' unless the provider explicitly asserts an instrument
    kind. Never defaults silently to 'common_stock'.
    """
    if not profile:
        return "unknown"
    if profile.get("isEtf"):
        return "etf"
    if profile.get("isFund"):
        # CONTRACT CHECK: verify what FMP means by isFund for this provider
        # version before trusting it as "mutual fund" (see step 6).
        return "mutual_fund"
    return "common_stock"
```

**Single source of truth:** every path (live ingestion, backfill, tests) calls
this function; there is no second classification implementation.

### 4. Use it from `ingest_company_profile()`

`ingest_company_profile()` (already re-added to `FundamentalsIngestion`) sets the
type alongside the other profile fields:

```python
company.instrument_type = classify_instrument(profile)
```

No separate `elif isEtf/isFund` block elsewhere.

### 5. Backfill existing rows via the same machinery

Do **not** loop `fmp.get_company_profile()` over N companies inline. Add a
batched backfill function that reuses `ingest_company_profile()` (which already
handles profile fetch + commit + logging):

- Select companies where `instrument_type == "unknown"`.
- Process in bounded batches with per-batch commit, per-row try/except +
  logging (mirrors `ingestion_worker.ingest_fundamentals`), and a small sleep
  between batches to respect FMP rate limits.
- Lives as a worker entry (`workers/ingestion_worker.py`) or a standalone
  backfill script invoked once; reuses `FundamentalsIngestion`, not a bespoke
  classifier.

This avoids N unbounded external calls and a partial-failure aborted
transaction.

### 6. Provider-contract verification (blocking)

Before finalizing `classify_instrument`, verify against the live FMP profile
payload for the provider/plan in use:

- Confirm `isEtf` is present and `true` for SPY/QQQ.
- Confirm `isFund` semantics (does it cover ETFs too, or only mutual funds?).
- Confirm a missing/empty profile yields no false `common_stock`.

If FMP does not reliably distinguish `mutual_fund` from `etf`, collapse both to
`fund` or keep only `etf`/`common_stock`/`unknown`. The enum must not claim
precision the provider does not supply.

### 7. Frontend — badge

`Companies.jsx`: next to the ticker, show a small neutral badge for non-stock
types (reuse `StatusChip` or an inline span). `common_stock` renders no badge
(clean default); `unknown` may render a muted "unclassified" marker.

### 8. Frontend — filter (fix the logic bug)

The filter must be **independent of the search term** (review item 7 — the
original draft returned early on empty search and never hid ETFs). Correct shape:

```jsx
const [showNonStock, setShowNonStock] = useState(false);

const filtered = companies.filter((c) => {
  // type gate first, independent of search
  if (!showNonStock && c.instrument_type !== "common_stock") return false;
  const q = search.trim().toLowerCase();
  if (!q) return true;
  return (
    (c.ticker || "").toLowerCase().includes(q) ||
    (c.name || "").toLowerCase().includes(q) ||
    (c.sector || "").toLowerCase().includes(q) ||
    (c.industry || "").toLowerCase().includes(q)
  );
});
```

Toggle label: **"Show non-stock instruments"** (not "Show ETFs & funds" —
narrower than the model, review item 8).

### 9. Analysis / fundamentals boundary guard

A `common_stock` vs non-stock discriminator is only half the fix. Add a guard at
the ingestion/analysis boundary so ETF/fund rows are not run through company
fundamentals + analysis unchanged:

- `workers/analysis_worker.run_company_analysis` / `recalculate_scores`: skip
  (or route differently) entities where `instrument_type != "common_stock"`.
- `FundamentalsIngestion.ingest_fmp_statements` / `ingest_sec_facts`: skip SEC
  filing/fundamental ingestion for non-stock types (an ETF has no XBRL financial
  statements in the company sense).

Decide explicitly: for MVP, **non-stock entities are tracked but excluded from
company-style fundamentals and analysis**. The guard lives in one place (a
predicate, e.g. `is_company_analysis_target(company)`), not scattered checks.

### 10. Tests

Contract tests (mirroring existing `tests/` style, but per instruction tests are
currently not the priority — add only the classifier unit tests):

- `classify_instrument` → AAPL profile = `common_stock`; SPY (`isEtf=True`) =
  `etf`; `isFund=True` = `mutual_fund`; `{}`/`None` = `unknown`.
- `ingest_company_profile` writes `instrument_type` on a stub.
- API `?type=` filter returns only matching type.

---

## Implementation order (as revised)

1. Migration `0022` (add column, `server_default="unknown"`, then drop default)
2. ORM `Company.instrument_type` + `CompanyResponse` schema field
3. `classify_instrument()` single classifier
4. Wire into `ingest_company_profile()`
5. Batched backfill reusing `ingest_company_profile()`
6. Provider-contract verification of `isEtf`/`isFund` (blocking)
7. Frontend badge
8. Frontend filter (corrected logic + label)
9. Non-stock analysis/fundamentals guard (one predicate)
10. Classifier unit tests

## Verdict

`instrument_type` on `companies` is the right minimal-change approach. The
corrections from review are: instrument (not "operating company") terminology;
`unknown` fallback instead of silently defaulting to `common_stock`; dropping
`index`/`crypto` until reliably classifiable; a single reusable classifier;
batched backfill reusing the ingestion path; a corrected FE filter; and a
fundamentals/analysis boundary guard so ETFs are not analyzed as companies.
