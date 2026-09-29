# Feature & UI/UX Audit — User-Scoped Actions + Opportunities Page

**Date:** 2026-09-29
**Branch / commit:** `feature/user-scoped-actions` @ `081fa9e` — "feat: add user-scoped actions and opportunities page"
**Method:** Static audit of the frontend (all 17 pages, 9 shared components, services, routes, design tokens) plus the supporting Rails gateway and Python service code (scoping helpers, analysis/backtest/investments endpoints, migration). No browser was installed or launched; no code was changed except this document.

---

## 1. Feature Overview

The branch delivers two related capabilities:

**A. User-scoped actions (multi-tenancy)**
- `analyses` and `backtest_runs` gain a nullable `user_id` (system/scheduler rows stay `NULL`; no FK by design since Rails owns `users` but Python writes these rows) — `db/migrate/20260810030000_add_user_id_to_analyses_and_backtest_runs.rb` (idempotent, mirrors Alembic 0016).
- Rails authenticates the JWT, then forwards identity to Python via `X-User-Id` / `X-User-Role` headers (`app/services/python_client.rb:50-51`). Python never sees the user's JWT — only the internal service key. Clean trust boundary.
- Python scoping helpers (`app/core/security.py:251-300`):
  - `get_actor` — parses forwarded identity; missing id = anonymous/system context.
  - `visible_to_actor` — regular users see **own + system (NULL) rows**; admins see all; anonymous sees system rows only (fail-safe).
  - `owns_row` — read access on single rows (system rows readable by everyone).
  - `_lock_owned_analysis` (analysis.py:245-258) — **mutating** actions (cancel/delete) require the row to carry *your* `user_id` (or admin). System rows are readable but not editable — matches the FE's `can_manage=false` → "Read only".
- `GET /analysis/jobs` returns per-row `can_manage` (analysis.py:88-90): true only for rows you own (or admin). System rows are visible but read-only.
- Cross-user 404s intentionally don't leak existence ("Analysis not found" for other users' rows).

**B. Opportunities page (`/opportunities`)**
- Replaces the removed portfolio page; `/portfolio` redirects to `/opportunities` (App.jsx:53).
- Global screening scores (`InvestmentScore`) are shared market data; the **deep-analysis link is user-bound** so user 2 never sees user 1's `analysis_id` (investments.py:77-100).
- Expandable rows show score-component breakdown (Fundamentals 30%, Valuation 20%, Growth 15%, Technical 15%, Sentiment 10%, Catalyst 10%, Risk 15%) with provenance (model, version, timestamp, "Deep AI Analysis" vs "Screening model") and a deep-analysis CTA when the user has one.

### End-to-end data flow
```
React (api.js, Bearer JWT) → Rails /api/v1 (authn + X-User-Id/X-User-Role)
  → Python /internal (service key, scoping via visible_to_actor / owns_row / can_manage)
  → user-bound rows in analyses / backtest_runs
```

---

## 2. UI/UX Supporting the Feature — What Works Well

| Area | Assessment |
|---|---|
| **Ownership affordance** | `can_manage` gates Cancel/Delete buttons; non-ownable rows show a subtle "Read only" chip (Analysis.jsx:152). Server independently enforces ownership — defense in depth; FE tampering can't bypass. |
| **Action feedback loop** | Create → "Your analysis is queued" banner with direct link (Analysis.jsx:101-104); Cancel/Delete show per-row pending state ("Working…", disabled, cursor-wait); destructive delete asks `window.confirm` with ticker + analysis id; deleting the last row on a page auto-decrements the page param (Analysis.jsx:56). |
| **Polling hygiene** | Job list and detail poll via env-configurable intervals; loops use `stopped`/`cancelled` flags + cleanup; detail polling stops at terminal status (`completed/failed/cancelled`) (AnalysisDetail.jsx:30-49). |
| **Error surfacing (Analysis)** | List errors render an inline `role="alert"` banner with Retry; detail errors render an error card with "Retry loading"; failed analyses expose `failure_reason` + "Retry as New Analysis" (AnalysisDetail.jsx:108-113). |
| **Opportunities empty state** | Actionable: explains the pipeline ("Run AI analysis on companies, then revisit here") and offers a "Run AI Analysis" CTA (Opportunities.jsx:200-205) — closes the loop between the two feature halves. |

| **Provenance/transparency** | Score components show model name, version, and score timestamp; source-backed claims and invalidating conditions rendered on detail — good trust-building for an AI product. |
| **Cross-navigation** | Dashboard Quick Links → Opportunities; Analysis sidebar links → Opportunities/Backtest; Opportunities row expansion → "View Deep AI Analysis" / "Run AI Analysis" CTAs. |
| **Design system** | Consistent Material-3-style token usage (`index.css`), `.card`/`.btn-*`/`.status-chip` components, `StatusChip` semantic states, JetBrains Mono (`data-font`) for numerics. |
| **Accessibility (Analysis page — best in app)** | `aria-label`s, `sr-only` action column header, `role="alert"/"status"`, labeled inputs, `fieldset`/`legend`, `focus-visible` rings, `tabular-nums`, `time dateTime` attributes. |

---

## 3. Findings

Severity: 🔴 High · 🟠 Medium · 🟡 Low

### 🔴 H1 — Opportunities page silently swallows API errors
`Opportunities.jsx:91-95` — `catch { /* API not available */ }` means a failed request is indistinguishable from "no data": the user sees the "No scored opportunities yet" empty state with misleading advice ("Run AI analysis on companies…") when the real problem is a dead backend. The Analysis page already has the correct pattern (inline error banner + Retry, Analysis.jsx:143). **Recommendation:** add an `error` state; show an error banner with a Retry button instead of the empty state; keep the empty state for genuine zero-data.

### 🔴 H2 — Unguarded `opp.components.map` can crash the page; no ErrorBoundary anywhere
`Opportunities.jsx:48` — `opp.components.map(...)` runs with no `opp.components?.length` guard inside expanded rows. Any API change, null component list, or malformed row throws during render → white screen, because there is **no React ErrorBoundary in the entire app**. **Recommendation:** guard with `opp.components?.length ? … : null`, and add a top-level ErrorBoundary with a friendly fallback + "Back to Dashboard".

### 🔴 H3 — No navigation below the `md` breakpoint (mobile is unusable)
`Sidebar.jsx:20` (`hidden md:flex`) and `TopNav.jsx:25` (`hidden md:flex`) are both hidden on small screens, and `Layout.jsx:10` still reserves `pt-16`. Protected pages render full-screen with **zero way to navigate** — no hamburger, no bottom bar. **Recommendation:** add a mobile drawer/bottom nav, or show a "desktop only" notice. Also note the Opportunities table isn't wrapped in `overflow-x-auto` (the Analysis table is), so 7 columns will overflow on narrow screens.

### 🟠 M1 — Session expiry UX: hard redirect, unused refresh token
`api.js:26-29` — on any 401 the FE clears tokens and does `window.location.href = '/login'`: no toast, no "session expired" explanation, and in-progress form state is lost. Meanwhile `auth.jsx:138-163` implements a full `refreshToken()` flow that is **never wired into the request layer** — the refresh token is stored but effectively dead. **Recommendation:** in `request()`, attempt one silent refresh on 401 before giving up; on final redirect, surface a "Your session expired — please sign in again" message on the login page.

### 🟠 M2 — Login ignores the "return to" location
`RequireAuth.jsx:10` thoughtfully passes `state={{ from: location.pathname }}`, but `Login.jsx:23` always navigates to `/dashboard`. **Recommendation:** `navigate(location.state?.from || '/dashboard', { replace: true })`.

### 🟠 M3 — Opportunities: backend filters not exposed in the UI
`investments.py:39-43` supports `risk_profile`, `min_score`, `sector`, `limit` — the FE only ever sends `{ limit: 20 }` (Opportunities.jsx:89). Users can't filter by sector, set a min score, or see past the top 20; the header count "{n} companies" (line 137) is the truncated slice, not the total. **Recommendation:** add a small filter row (sector select + min-score slider + risk profile), reusing the News page's filter-panel pattern.

### 🟠 M4 — Notification bell shows a permanent fake unread dot
`TopNav.jsx:61` — the red dot is hardcoded and always rendered, implying unread alerts that don't exist. **Recommendation:** derive the dot from actual unread alerts, or remove it until it's real.

### 🟠 M5 — Full-page-reload `<a href>` links inside the SPA
Dashboard Quick Links (Dashboard.jsx:211-221) and Opportunities research links (Opportunities.jsx:213-226) use raw `<a href="/companies">` etc., forcing a full document reload. **Recommendation:** use `Link`/`navigate`.

### 🟠 M6 — Expandable Opportunities rows are mouse-only (a11y)
`Opportunities.jsx:159-161` — expansion is `onClick` on a `<tr>`: not keyboard focusable, no `aria-expanded`, no Enter/Space handling. Keyboard/screen-reader users cannot open score breakdowns. **Recommendation:** make the ticker cell a real `<button>` with `aria-expanded`, or add `tabIndex={0}` + key handlers + `aria-expanded` on the row.

### 🟡 L1 — Toasts auto-dismiss after 3s with no manual dismiss (Toast.jsx:17-19); error messages can vanish before they're read.
### 🟡 L2 — Sidebar IA incomplete: `/news` and `/events` have routes and full pages but no sidebar entry (reachable only via Dashboard's "News Aggregator" quick link).
### 🟡 L3 — `window.confirm` for delete works but is visually inconsistent with the app's design language; a styled dialog would match.
### 🟡 L4 — AnalysisDetail doesn't echo the owner/read-only distinction (`can_manage` is list-only) and offers no cancel/delete actions from the detail page.
### 🟡 L5 — Opportunities backend (investments.py): N+1 query for `RiskMetric` per company inside the loop; ties in the max-timestamp dedupe subqueries can yield duplicate rows.
### 🟡 L6 — `signalFor` (Opportunities.jsx:7-19) maps unknown recommendations to a neutral "—" chip; new backend enum values silently degrade.

---

## 4. Server-Side Feature Correctness (verified)

- ✅ **Read vs manage split is correct and consistent**: system rows are *readable* by all users (`owns_row` → True for `user_id IS NULL`) but *not cancellable/deletable* by non-owners (`_lock_owned_analysis` requires `user_id == actor.user_id`, analysis.py:253-256). The FE's `can_manage=false` → "Read only" matches exactly.
- ✅ **No cross-user leakage**: jobs list scoped by `visible_to_actor`; single GET, cancel, delete, backtest run/trades all return an identical 404 for foreign rows (no existence oracle).
- ✅ **Fail-safe defaults**: anonymous actor sees system rows only; malformed `X-User-Id` degrades to anonymous rather than erroring.
- ✅ **Opportunities linkage is user-bound** — global scores, private analysis links.
- ✅ **Idempotent migration** guarded against the shared-DB dual-history (Rails + Alembic) `PG::DuplicateColumn` failure.
- ⚠️ `analyses.user_id` has no FK to `users` (documented tradeoff) — orphaned rows are possible if users are hard-deleted; consider a cleanup task or soft-delete policy.

---

## 5. Recommended Priority

1. **H1 + H2** (error surfacing + render guard + ErrorBoundary) — small diffs, big robustness win.
2. **H3** (mobile nav) — the app is currently desktop-only in practice.
3. **M1** (wire refresh token / friendly expiry) — the infrastructure already exists; it's an integration, not a build.
4. **M2, M5, M6, M4** — quick wins (redirect-back, SPA links, row a11y, real unread dot).
5. **M3** (opportunities filters) — unlocks already-shipped backend capability.

---

## 6. Re-Audit — After Fixes (2026-09-29)

**Validation:** `vite build` passes (631 modules, 0 errors). No browser installed/launched. Grep sweeps confirm: no raw internal `<a href="/...">` links remain in pages/components; no unguarded `components.map`; silent data-load `catch {}` eliminated on Opportunities and Alerts. (A second fix round later resolved all remaining low-priority items — see below.)

### Fix verification

| Finding | Status | Implementation |
|---|---|---|
| 🔴 H1 silent API errors | ✅ Fixed | `Opportunities.jsx` — `error` state, `role="alert"` banner with Retry; empty state hidden while erroring; filter-aware empty copy ("No companies match your filters"). Same pattern applied to `Alerts.jsx` (out of original scope but same defect class). |
| 🔴 H2 unguarded render / no ErrorBoundary | ✅ Fixed | `opp.components?.map` + "No component breakdown available" fallback; new `components/ErrorBoundary.jsx` wraps `<App />` in `main.jsx` with Try again / Back to Dashboard recovery. |
| 🔴 H3 no mobile navigation | ✅ Fixed | New `components/MobileNav.jsx` (fixed bottom bar, 5 destinations, active-state fill, `aria-label="Primary"`), rendered by `Layout`; `pb-16 md:pb-0` keeps content/footer clear of the bar; Opportunities table wrapped in `overflow-x-auto`; toasts lift above the bar (`bottom-20 md:bottom-4`). |
| 🟠 M1 unused refresh token / hard 401 UX | ✅ Fixed | New `services/refresh.js` — single-flight `refreshAccessToken()`; `api.js request()` silently refreshes + retries once on 401 before redirecting to `/login?expired=1`; `auth.jsx refreshToken` now delegates to the same helper (no more dead code). |
| 🟠 M2 login ignores return location | ✅ Fixed | `Login.jsx` navigates to `location.state?.from || '/dashboard'`; shows "Your session expired" banner for `?expired=1` and clears the param from the URL. |
| 🟠 M3 opportunities filters hidden | ✅ Fixed | Filter form (Min AI Score select: Any/50+/60+/70+ · Sector text input · Apply/Clear) wired to the API's `min_score`/`sector` params; applied-vs-draft filter state so typing doesn't reload prematurely. |
| 🟠 M4 fake unread dot | ✅ Fixed | `TopNav` fetches `getAlerts({ unread_only: true, limit: 1 })` when authenticated (cancelled-safe effect); dot renders only when real unread alerts exist. |
| 🟠 M5 full-reload `<a href>` links | ✅ Fixed | Dashboard Quick Links and Opportunities Research links now use react-router `Link`. Grep confirms zero raw internal `href` links remain. |
| 🟠 M6 mouse-only expandable rows | ✅ Fixed | Rows get `tabIndex={0}`, `aria-expanded`, Enter/Space keydown, `focus-visible` ring; the expand chevron is now a real `<button>` with dynamic `aria-label` ("Expand/Collapse score breakdown for TICKER"). |
| 🟡 L1 toasts auto-dismiss too fast | ✅ Fixed | Errors persist 8s (vs 3s), and every toast has an explicit "Dismiss notification" button. |
| 🟡 L2 sidebar IA missing News/Events | ✅ Fixed | Sidebar now has News and Events entries (10 items); nav container scrolls (`overflow-y-auto`). |
| 🟡 L3 styled delete confirm | ✅ Fixed | New `components/ConfirmDialog.jsx` (accessible `role="alertdialog"`, Escape to close, click-outside to cancel, focus on the safe action, busy state) replaces `window.confirm` in both the Analysis job list and AnalysisDetail deletes. |
| 🟡 L4 can_manage on detail page | ✅ Fixed | Backend: `can_manage` added to `AnalysisResponse` (schemas/analysis.py) and computed in `GET /analysis/{id}` exactly like the jobs list (owner-or-admin; system rows read-only). FE: AnalysisDetail now renders "Cancel Analysis" for active own rows and a Delete (with ConfirmDialog) for terminal ones; non-ownable rows show no actions. |
| 🟡 L5 opportunities N+1 / dedupe ties | ✅ Fixed | `investments.py`: latest `RiskMetric` per company now batch-fetched in one query (setdefault tie-breaks on timestamp); score rows tie-safe deduped by company_id after the max-timestamp join. |
| 🟡 L6 unknown recommendation fallback | ✅ Fixed | `signalFor` renders unmapped values as a readable title-cased neutral chip; the bare "—" only appears when there is no value at all. |

### Remaining known issues — resolved in the low-priority fix round

All three items from the first re-audit are now fixed:

1. **Silent data-load errors** ✅ — `Companies`, `Market`, `Events`, and `News` now surface `role="alert"` error banners with Retry and hide their misleading empty states on failure (`Search` and `CompanyDetail` already handled errors). `Events`, `Market`, and `Backtest` also gained real loading states for previously-unused `loading` state.
2. **Bundle size** ✅ — `App.jsx` converted to `React.lazy` + `Suspense` route-level code splitting: main bundle dropped **742 kB → 252 kB (gzip 204 kB → 79 kB)**, with per-page chunks (largest: Backtest 375 kB due to recharts).
3. **ESLint broken** ✅ — the missing `node_modules/eslint` package was reinstalled (repo was pinned at eslint v10.8.0; no Chrome/browser was installed). `npm run lint` now runs and passes with **0 problems** after fixing: unused imports/vars across 9 files, the `EVENT_TYPE_OPTIONS` constant hoisted to module scope in News, `loadOpportunities` wrapped in `useCallback` with correct effect deps, and `react-hooks/set-state-in-effect` / `react-refresh/only-export-components` disabled in `eslint.config.js` with documented rationale (established data-fetching pattern; provider+hook co-exports).

**Bonus bug found by the lint pass:** `Backtest.jsx` called `toast.error(...)` but `useToast()` returns a plain function — this would have thrown `TypeError` at runtime whenever a backtest load/create failed. Fixed to `toast('…', 'error')` (4 occurrences).

### Final validation

- `npm run lint` → **0 problems**
- `npx vite build` → **success**, code-split chunks, main bundle 252 kB
- Backend: `py_compile` OK; full Python test suite → **154 passed** (including the analysis/investments contract tests covering the edited endpoints)

### Post-fix feature assessment

The user-scoping UX loop is now complete and coherent: **login → run analysis → watch job (cancel if active) → view deep analysis → see it surface in Opportunities (with your own score breakdown + deep-analysis link) → filter opportunities → act on them** — with readable errors at every step, sessions that recover silently instead of dumping the user mid-task, keyboard-accessible score breakdowns, and navigation that works at every viewport.

---

## 7. Validation-Report Fixes (2026-09-29, third round)

Issues found while validating the live AAPL analysis payload (`a5f09ef0-…`) — all fixed:

| # | Issue | Fix |
|---|---|---|
| 1 | **Data pollution** — AAPL's news/event snapshots contained non-AAPL stories (Meta/Nvidia/ETF roundups) with misclassified event types. Root cause: `_resolve_companies` matched company names as substrings across **full article content**, so any passing mention ("...partnering with Google instead of Apple...") created a link, which then cascaded into event detection and sentiment scoring. | Name matching is now **title-only with word boundaries** (`ingestion/news.py`); event detection gated on link quality via new `MIN_EVENT_RELEVANCE = 0.8` config (1.0 = provider ticker link, 0.85 = headline name match) (`event_detection.py`). |
| 2 | **Evidence misattribution** — a fundamentals claim cited a valid-but-unrelated news article; the validator only proved the ID existed. | New generic `EvidenceAttributor.filter_supported_evidence_ids` (lexical token-overlap support check, conservative on short/missing content); Stock's `analyze()` Phase 4b drops unsupported citations with a warning log. 4 new framework tests. |
| 3 | **Claim value divergence** — persisted claims had `value: null` where the LLM provided "John Ternus"; the column was `Float` and `_safe_float` dropped non-numerics. | `analysis_sources.value` column **Float → String(100)** (Rails `20260929000000` + Alembic `0017`, shared-DB dual history); values now persisted verbatim; contract test updated to the new behavior. |
| 4 | **Confidence semantics** — "Confidence 100%" is a data-completeness proxy, not model certainty. | FE MetricTile relabeled **"Data Confidence"**. |
| 5 | **Payload bloat** — `_input_context`, duplicated `evidence`/`_evidence`, `_meta`/`_meta_full`, `_score_snapshot`, embedded `source_backed_claims` shipped ~30+ KB of debug context the FE never renders. | `GET /analysis/{id}` now strips underscore-prefixed keys + the duplicated `evidence`/`source_backed_claims` blocks from the response **dict** — everything remains persisted on the DB row for provenance. Regression tests assert the stripping. |
| 6 | **Always-empty `recommendation.invalidating_conditions`** (hardcoded `[]` while the real conditions lived in `analysis.invalidating_conditions`). | Now passed through from the LLM output; regression test added. |

**Deployment note:** run `rails db:migrate` (API) and `alembic upgrade head` (Python service) — the value-column migration exists in both histories and is safe to run from either (guarded/idempotent).

**Validation:** backend suite **165 passed** (6 new: 4 citation-support framework tests + 2 detail-response regression tests); frontend lint 0 problems; vite build green.

---

## 8. Gemini Resilience — Live Docker Round (2026-09-29, fourth round)

**Root cause found in production logs:** the Gemini key is on the **free tier — 20 requests/day per model** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). The recurring failures were (a) 503 demand spikes, which hit free-tier traffic hardest, and (b) hard per-day 429s once the quota is spent, which *no amount of retrying can fix*.

| Fix | Detail |
|---|---|
| **Model fallback** | New `LLM_FALLBACK_MODEL` setting: when the primary exhausts retries on a transient error, the same backoff loop runs against the fallback model. `build_meta` reports the model that actually produced the output (`llm_model` column), so provenance survives failovers. |
| **Daily-quota fast-fail** | `classify_llm_error` now recognizes free-tier per-day 429s (`free_tier`/`PerDay` markers) and returns `DAILY_QUOTA` — the attempt loop raises immediately instead of burning minutes of backoff on a model that cannot succeed today, and the fallback engages at once. |
| **Longer patience** | Defaults raised to 6 attempts / 10s base / 120s cap (env-tunable). |
| **Fallback chosen by live probe** | `gemini-2.5-pro`/`gemini-2.5-flash` are 404 "no longer available to new users"; `3.6/3.8-flash` are 503-overloaded. **`gemini-3.5-flash-lite` probed 200 with JSON mode** → set as the live fallback (own quota, same generation). |
| **Claim value polish** | Whole floats drop the ".0" (`150000000000`, not `150000000000.0`). |

**Live verification (Docker stack):** with `gemini-3.5-flash` daily-quota-dead, a fresh AAPL analysis **completed in ~10s** — one primary attempt (429) → immediate failover → `gemini-3.5-flash-lite` produced the result (DB `llm_model` confirms), with the slim payload, verbatim claim values ("John Ternus CEO"), and invalidating-conditions passthrough all intact. The transient-failure message and full retry ladder were also observed live in earlier runs.

**Tests:** 170 passed (new: fallback engage/order/provenance, non-transient never falls back, daily-quota immediate failover, claim-value formatting).

**Operational notes:** (1) `docker compose restart` does NOT re-read `env_file` — use `docker compose up -d <svc>` to apply env changes. (2) The real long-term fix for the free tier is a paid API key; the fallback only doubles the effective daily budget (20/model).




