import test from 'node:test';
import assert from 'node:assert/strict';
import { readJson } from '../src/services/http.js';

const response = (body, { status = 200, type = 'application/json' } = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: { get: (name) => (name.toLowerCase() === 'content-type' ? type : null) },
  text: async () => body,
});

// Audit regression: an nginx 502 page, a Rails HTML error page, or the SPA
// fallback reached the client as text/html. It used to surface as
// "Unexpected token '<', "<html> <h"... is not valid JSON" with no indication
// of what actually happened.
test('JSON responses pass through unchanged', async () => {
  const parsed = await readJson(response('{"data":{"ticker":"AAPL"}}'));
  assert.deepEqual(parsed, { data: { ticker: 'AAPL' } });
});

test('an HTML error page explains the situation instead of a syntax error', async () => {
  const html502 = '<html>\r <head><title>502 Bad Gateway</title></head></html>';
  await assert.rejects(
    readJson(response(html502, { status: 502, type: 'text/html' })),
    (error) => {
      assert.ok(!String(error.message).includes('<'), 'no raw HTML in message');
      assert.ok(!String(error.message).includes('Unexpected token'), 'no JSON.parse jargon');
      assert.ok(String(error.message).includes('unreadable response'), 'says the response was unreadable');
      assert.equal(error.status, 502);
      return true;
    }
  );
});

test('a 200 HTML page (misrouted SPA fallback) is reported as misrouting', async () => {
  const html = '<!doctype html> <html lang="en">';
  await assert.rejects(
    readJson(response(html, { status: 200, type: 'text/html' })),
    (error) => {
      assert.ok(String(error.message).includes('misrouted or unavailable'));
      return true;
    }
  );
});

test('malformed JSON still fails, but with the status attached', async () => {
  await assert.rejects(
    readJson(response('{broken', { status: 200 })),
    (error) => {
      assert.equal(error.code, 'INVALID_JSON');
      assert.equal(error.status, 200);
      return true;
    }
  );
});
