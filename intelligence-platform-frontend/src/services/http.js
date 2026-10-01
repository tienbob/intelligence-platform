// Shared response reader.
//
// A non-JSON body must never surface as `Unexpected token '<', "<html> <h"...
// Those pages come from nginx (502 Bad Gateway), Rails' HTML error pages, or
// the SPA fallback, and they used to crash the caller with a JSON syntax error
// that said nothing about the real problem. This reports what actually
// happened instead, so a misrouted or down service is diagnosable.
export async function readJson(res) {
  const contentType = (res.headers.get('content-type') || '').toLowerCase();
  const text = await res.text();
  if (!contentType.includes('json')) {
    const error = new Error(
      res.ok
        ? `Unexpected non-JSON response (HTTP ${res.status}). The API is misrouted or unavailable.`
        : `HTTP ${res.status}: the API returned an unreadable response. The service may be unavailable.`
    );
    error.code = 'NON_JSON_RESPONSE';
    error.status = res.status;
    throw error;
  }
  try {
    return JSON.parse(text);
  } catch {
    const error = new Error(`HTTP ${res.status}: malformed JSON response.`);
    error.code = 'INVALID_JSON';
    error.status = res.status;
    throw error;
  }
}
