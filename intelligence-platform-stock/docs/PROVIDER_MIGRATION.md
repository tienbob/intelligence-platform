# Replacement for ISP-blocked Massive

Active providers: Twelve Data for OHLCV, Finnhub for quotes/news/profiles, SEC for normalized US USD financial statements. FMP remains a fallback and the market-movers provider. Massive's adapter and historical provenance remain for compatibility; active routing no longer calls it.

Set TWELVE_DATA_API_KEY and FINNHUB_API_KEY in the root .env. Set SEC_USER_AGENT to your organization and actual contact email. Compose already passes .env to Python, worker and scheduler; recreate those services after updating it. Run Alembic migration 0021 before starting updated services; statement uniqueness now includes period_type. Re-ingest fundamentals to recover previously skipped statements.

Twelve Data Basic reserves 8 credits/minute and 800/day using atomic Redis counters shared across processes and retries. Exhaustion fails immediately rather than waiting inside API requests. Historical responses are cached by the existing provider cache. Redis quota failures fail closed. With Redis disabled, budgets are process-local only; keep Redis enabled in multi-process deployments. Historical bars are split-adjusted, not dividend-adjusted total returns.

Finnhub general news search filters the available feed locally; it is not a full historical keyword search. Finnhub quote responses do not include volume. Market movers still require FMP endpoint entitlement. SEC normalization covers USD US-GAAP annual and standalone quarterly durations, omits YTD durations, and does not derive missing standalone quarters from YTD values. Non-US and non-USD fundamentals may require FMP. Confirm provider display/redistribution rights for your deployment.

Live verification requires keys and connectivity from the affected server. Check a quote, a 365-day OHLCV history, company news, and canonical annual/quarterly statements before deployment. Tests mock external requests and do not establish account entitlements or network reachability.

Scheduled history uses stable UTC date bounds and completed daily bars. Repeated runs share the cached response; missing/old histories are processed first and FMP is used when configured. On quota exhaustion, remaining work is deferred. This pipeline does not refresh intraday quotes. API-level errors are validated before caching; the new cache namespace bypasses previously cached errors.
