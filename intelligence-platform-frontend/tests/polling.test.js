import test from 'node:test';
import assert from 'node:assert/strict';
import { startPolling } from '../src/services/polling.js';

function visibility(hidden = false) {
  const target = new EventTarget();
  target.hidden = hidden;
  target.change = (value) => { target.hidden = value; target.dispatchEvent(new Event('visibilitychange')); };
  return target;
}
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

test('hidden tabs wait for visibility and never overlap pending loads', async () => {
  const page = visibility(true);
  let calls = 0;
  let finish;
  const stop = startPolling(() => {
    calls++;
    return new Promise(resolve => { finish = resolve; });
  }, 10000, page);
  try {
    assert.equal(calls, 0);
    page.change(false);
    assert.equal(calls, 1);
    page.change(true); page.change(false);
    assert.equal(calls, 1);
    finish(); await settle();
    page.change(true); page.change(false);
    assert.equal(calls, 2);
    finish();
  } finally { stop(); }
});

test('cleanup invalidates in-flight responses and removes visibility listener', async () => {
  const page = visibility();
  let active;
  let finish;
  let calls = 0;
  const stop = startPolling((isActive) => {
    calls++; active = isActive;
    return new Promise(resolve => { finish = resolve; });
  }, 1, page);
  stop();
  assert.equal(active(), false);
  finish(); await settle();
  page.change(false);
  assert.equal(calls, 1);
});

test('terminal results do not resume on tab visibility', async () => {
  const page = visibility();
  let calls = 0;
  const stop = startPolling(async () => { calls++; return false; }, 1, page);
  try {
    await settle();
    page.change(true); page.change(false);
    assert.equal(calls, 1);
  } finally { stop(); }
});
