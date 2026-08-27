/**
 * Shared runtime configuration sourced from Vite environment variables.
 *
 * All values are read once at import time. To change a value, update the
 * corresponding VITE_* variable in .env and restart the dev server (or
 * rebuild for production).
 *
 * @see .env.example for available variables and their defaults.
 */

/** Dashboard auto-refresh interval in milliseconds (0 = disabled). */
export const REFRESH_DASHBOARD_MS = Number(
  import.meta.env.VITE_REFRESH_DASHBOARD_MS ?? 30000,
);

/** Analysis jobs list auto-refresh interval in milliseconds (0 = disabled). */
export const REFRESH_ANALYSIS_JOBS_MS = Number(
  import.meta.env.VITE_REFRESH_ANALYSIS_JOBS_MS ?? 5000,
);

/** Analysis detail polling interval in milliseconds (0 = disabled). */
export const REFRESH_ANALYSIS_DETAIL_MS = Number(
  import.meta.env.VITE_REFRESH_ANALYSIS_DETAIL_MS ?? 5000,
);