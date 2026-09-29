# Frontend Audit — Market Intelligence Platform

**Date:** 2026-08-13
**Scope:** Current state of the frontend (`market-intelligence-frontend`) — what each page shows and what the user can do.
**Method:** Read every page, the shared components, the API service layer, routing, and app config. No code changes were made for this audit.

---

## 1. Architecture Overview

- **Framework:** React (v19) + React Router (v7) + Vite (v8) + Tailwind CSS v4.
- **State:** Local React state only (`useState`/`useEffect`). No Redux/Zustand.
- **API access:** A single service layer (`src/services/api.js`) that talks to a Rails gateway at `/api/v1`. The gateway proxies to a Python intelligence service for market/analysis data and owns auth + portfolio CRUD.
- **Auth:** `useAuth` (context) + `RequireAuth` route guard. Tokens stored via `services/token.js`.
- **Layout:** `Layout` component wraps protected pages with `Sidebar` (desktop nav), plus `TopNav` and `Footer`. Public pages (`/`, `/login`, `/register`) render without the app shell.

### Routing (protected unless noted)
| Route | Page | Access |
|---|---|---|
| `/` | Landing | Public |
| `/login`, `/register` | Login / Register | Public |
| `/dashboard` | Dashboard | Protected |
| `/market` | Market Overview | Protected |
| `/companies` | Companies | Protected |
| `/companies/:ticker` | Company Detail | Protected |
| `/search` | Search | Protected |
| `/opportunities` | Opportunities (AI-scored) | Protected |
| `/portfolio` | Redirect → `/opportunities` | Protected |
| `/analysis` | AI Analysis Jobs | Protected |
| `/analysis/:analysisId` | Analysis Detail | Protected |
| `/backtest` | Backtesting | Protected |
| `/alerts` | Alerts | Protected |
| `/news` | News & Event Intelligence | Protected |
| `/news/:id` | News Detail | Protected |
| `/events` | Events | Protected |
| `/events/:id` | Event Detail | Protected |

---

## 2. Shared UI Components

- **`MetricTile`** — a label + value + icon card used across dashboards (score/value metrics).
- **`ProgressBar`** — colored horizontal bar for scores/weights (supports `size="sm"|"lg"`, `showLabel`).
- **`StatusChip`** — small colored pill for statuses (bullish/bearish/neutral, queued/running/completed, high/medium/low, etc.).
- **`Toast` / `useToast`** — global ephemeral notifications.
- **`RequireAuth`** — redirects unauthenticated users to `/login`.
- **`Sidebar`** — persistent left nav with the following items: **Dashboard, Markets, Companies, Search, Investment Intelligence, AI Jobs, Backtest, Alerts.** (The "Investment Intelligence" item routes to `/portfolio`.) Also has placeholder "Upgrade Analytics", "Support", "Documentation" buttons that show a "coming soon" toast.
- **`TopNav` / `Footer`** — layout chrome.

---

## 3. Page-by-Page: What It Shows & What You Can Do

### 3.1 Landing (`/`) — Public
- **Shows:** Marketing hero ("AI-Powered Market Research & Investment Intelligence"), three feature cards (Market Intelligence, AI Research & Scoring, Portfolio Optimization), and a sign-in CTA.
- **Can do:** Navigate to Register or Login.

### 3.2 Login (`/login`) & Register (`/register`) — Public
- **Shows:** Email/password forms.
- **Can do:** Authenticate; on success redirect to `/dashboard`. Registration creates an account.

### 3.3 Dashboard (`/dashboard`)
- **Shows:** Market trend indicator (bullish/bearish), volatility, VIX with a mini gauge, a grid of major indices, a **Top Movers** table (ticker, price, change %, volume), a **Market Alerts** feed (up to 5), and Quick Links.
- **Can do:**
  - Auto-refresh every `REFRESH_DASHBOARD_MS` (default 30s).
  - Click a top mover → company detail.
  - "New Alert" → jumps to Alerts page. "Export" → "coming soon" toast.
  - Quick links: Deep Analysis, Portfolio Tools, News Aggregator.
  - Independent fetches so one slow API never blocks the others.

### 3.4 Market (`/market`)
- **Shows:** Market Trend, Volatility, Risk Level, Economic Regime metric tiles; a **Macro Environment** panel (Fed Funds Rate, 10Y Treasury, CPI, Unemployment, VIX, Yield Curve); **Major Events**; and **Top Movers** (score-based).
- **Can do:** Manual refresh. View market + macro intelligence in one place.

### 3.5 Companies (`/companies`)
- **Shows:** A searchable table of tracked companies: Ticker, Name, Exchange, Sector, Industry, Market Cap.
- **Can do:** Client-side filter by ticker/name/sector/industry; click a row → company detail.

### 3.6 Company Detail (`/companies/:ticker`)
- **Shows:** Stock quote header (name, price, change %, volume); **Price History** table (OHLCV, last 20 rows); **Technical Indicators** (RSI, MACD, SMAs, Bollinger, ATR, volatility, momentum, drawdown); **Financial Statements** (revenue, gross profit, op income, net income, EPS, FCF); **Financial Metrics** (P/E, P/S, P/B, EV/EBITDA, ROE/ROA, margins, growth, leverage).
- **Can do:** Back to companies; view quote/technical/fundamental data. (Data fetched via `Promise.allSettled` so partial failures don't break the page.)

### 3.7 Search (`/search`)
- **Shows:** A search form, a stock-quote result card (name, price, change %, volume, last-updated) when a valid quote is found, or a filtered companies table otherwise.
- **Can do:** Search by ticker or company name. It first tries `getStockQuote(ticker)`; if that fails, it fetches companies and filters client-side by ticker/name.

### 3.8 Investment Intelligence (`/portfolio`, nav label "Investment Intelligence") — **AI research / opportunities workspace**
- **Shows:**
  - **AI Investment Opportunities** table: Ticker, AI Score (with progress bar), Risk, Volatility, Sector, Signal (derived from the backend's recommendation, e.g. WATCH/NEUTRAL/CAUTION). This is the research showcase, driven by the investment-scoring backend.
  - **Research** quick actions: Browse Companies, AI Analysis Jobs.
- **Can do:**
  - Click an opportunity row → that company's detail page.
  - Refresh; "Run AI Analysis" → `/analysis`.
- **Note:** The heavy portfolio-management UI (Add/Edit/Delete holdings, Rebalance, Drift Alerts, Record Snapshot, Allocation History, optimized-result cards) has been **removed entirely from the frontend and backend** per the product pivot to showcase AI research. Only the stateless optimizer remains in the backend for future use.

### 3.9 AI Analysis Jobs (`/analysis`)
- **Shows:** Metric cards (Active/Queued, Total Jobs, Completed, Failed); an **Execution Queue** table (job id, ticker, status, score, created time, actions); a **"Deploy New Agent"** form (ticker, time horizon, data-inclusion toggles: news/fundamentals/technical/macro); a **Quick Actions** panel (links to Portfolio and Backtest).
- **Can do:**
  - Create an AI company analysis (queues a job).
  - Cancel active jobs; delete completed/failed records.
  - Auto-refresh list every `REFRESH_ANALYSIS_JOBS_MS` (default 5s) while jobs are active.
  - Click a row → analysis detail.

### 3.10 Analysis Detail (`/analysis/:analysisId`)
- **Shows:** Header with ticker, status, analysis id, created time, recommendation chip; metric tiles (Investment Score, Risk Score, Confidence, Overall Confidence); **LLM panels**: Summary, Investment Thesis, Market Interpretation, Bull Case / Bear Case, Catalysts / Risks, Causes; sidebar: **Recommendation** (reasons/risks), **Confidence Breakdown** (data/quantitative/LLM/overall), **Source-Backed Claims**, and **Invalidating Conditions**.
- **Can do:**
  - View the full AI-generated research report with evidence.
  - Auto-polls every `REFRESH_ANALYSIS_DETAIL_MS` (default 5s) until the job reaches completed/failed.
  - Back to AI jobs.

### 3.11 Backtesting (`/backtest`)
- **Shows:** List of backtest runs (name, strategy, status, period, capital); a **Create Backtest Run** form (name, strategy: Equal Weight / Momentum / Mean Reversion, benchmark, start/end dates, initial capital, comma-separated tickers); run detail with **Performance Metrics** (Total Return, Sharpe, Max Drawdown, Win Rate), **Benchmark Comparison** (strategy vs benchmark return, alpha, beta), and a **Trades** table; plus **Point-in-Time Snapshots**.
- **Can do:**
  - Create a new backtest run.
  - Click a run → view metrics, benchmark comparison, and per-trade detail.
  - Refresh.

### 3.12 Alerts (`/alerts`)
- **Shows:** A **Create Alert** form (optional ticker, alert type, severity, message) and an **Alert Feed** table (ticker, type, severity, message).
- **Can do:**
  - Create a new alert (types: price, volume anomaly, news, SEC filing, earnings, risk change, score change, portfolio concentration).
  - Dismiss (mark read) an alert.
  - Auto-loads alerts (limit 50).

### 3.13 News & Event Intelligence (`/news`)
- **Shows:** A left **Intelligence Filters** panel (ticker symbol input, event-type checkboxes, a min-impact-score slider) and a **VIX widget**; a central **Event Timeline** (events with ticker, time, type, description, impact score, confidence, and colored markers); and a **Correlated News** feed (source, date, sentiment badge, title, summary).
- **Can do:**
  - Filter by ticker, event types (Earnings, Regulatory/Legal, Analyst, Management, Macro, Corporate), and minimum impact score.
  - Click a news article → news detail.
  - "Export" → "coming soon" toast.
  - The event type filter is applied client-side; a mock-data label shows when no events match.

### 3.14 News Detail (`/news/:id`) & Event Detail (`/events/:id`)
- **Shows/does:** Detail views for a single news article and a single event (navigable from their list pages). (Back + full content.)

### 3.15 Events (`/events`)
- **Shows/does:** List of market events (complementary to the News page's timeline), with the same event-type/intelligence filtering and detail navigation.

---

## 4. What the App Cannot Do (currently)

- **No portfolio management** — add/edit/delete holdings, rebalance, drift alerts, snapshots, allocation history, and portfolio CRUD have been removed from the frontend, backend, and scheduler. Only the stateless optimizer is retained for future use. The `/portfolio` page is now a pure AI opportunities/research view.
- **Intraday/live pricing interaction** — prices are daily bars updated by a background worker; the UI shows the latest daily close, not a live tape.
- **Manual profit marking** — profit/P&L is computed on read from the latest `stock_prices.close` vs holding entry price; the UI does not persist/update a `current_price` column.
- **Export / Upgrade / Support / Documentation** — all show "coming soon" toasts (no real functionality).
- **User-facing settings / watchlists** — there's no watchlist or preference management in the FE.

---

## 5. Configuration Flags (`src/config.js`)

Read from Vite env vars at import time (defaults noted):
- `REFRESH_DASHBOARD_MS` — Dashboard auto-refresh (default 30000; 0 disables).
- `REFRESH_ANALYSIS_JOBS_MS` — Analysis jobs list refresh (default 5000).
- `REFRESH_ANALYSIS_DETAIL_MS` — Analysis detail polling (default 5000).

---

## 6. Observations & Notes

- **Strong data-diversity:** The FE surfaces market, macro, fundamental, technical, news, event, AI-scoring, backtesting, and alerting data — a wide range of the platform's capabilities.
- **AI showcase lives in Analysis + AnalysisDetail:** This is where the investment-thesis, bull/bear, catalysts, risks, source-backed claims, and recommendation content are rendered — the core "AI market intelligence" story.
- **The `/portfolio` page is labeled "Investment Intelligence"** in the nav and leads with AI-scored opportunities, aligning with a research-forward product story rather than a portfolio-manager UI.
- **Auto-refresh is env-configurable** and spread across Dashboard / Analysis / AnalysisDetail.
- **Resilient data loading** (Promise.allSettled on Company Detail; independent fetches on Dashboard) means partial provider failures degrade gracefully rather than breaking a page.