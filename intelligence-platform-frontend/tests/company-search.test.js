import test from 'node:test';
import assert from 'node:assert/strict';
import { createCompanySearch } from '../src/services/companySearch.js';

const pending = () => Object.assign(new Error('AMD is not tracked yet; ingestion has started.'), { status: 404 });

test('pending import survives a gateway failure and automatically displays the company', async () => {
  const states = [];
  let calls = 0;
  const company = { ticker: 'AMD', name: 'Advanced Micro Devices' };
  const poll = createCompanySearch('AMD', {
    getCompanies: async () => ({ companies: [] }),
    getCompany: async () => {
      if (++calls === 1) throw Object.assign(new Error('Gateway timeout'), { status: 504 });
      return company;
    },
    getStockQuote: async () => { throw pending(); },
    update: state => states.push(state),
  });
  assert.equal(await poll(() => true), true);
  assert.equal(await poll(() => true), true);
  assert.equal(await poll(() => true), false);
  assert.deepEqual(states, [
    { importing: true }, { importing: true },
    { results: { type: 'companies', data: [company] } },
  ]);
});

test('a search replaced while awaiting a response cannot update the new search', async () => {
  let finish;
  let active = true;
  const states = [];
  const poll = createCompanySearch('AMD', {
    getCompanies: () => new Promise(resolve => { finish = resolve; }),
    getStockQuote: async () => { throw new Error('must not run'); },
    update: state => states.push(state),
  });
  const request = poll(() => active);
  active = false;
  finish({ companies: [{ ticker: 'AMD' }] });
  assert.equal(await request, false);
  assert.deepEqual(states, []);
});

test('an ordinary missing ticker is an error, not a perpetual import', async () => {
  const states = [];
  const poll = createCompanySearch('BAD', {
    getCompanies: async () => ({ companies: [] }),
    getStockQuote: async () => { throw Object.assign(new Error('Unknown ticker'), { status: 404 }); },
    update: state => states.push(state),
  });
  assert.equal(await poll(() => true), false);
  assert.ok(states[0].error);
});

test('failed ingestion replaces importing with its failure and stops polling', async () => {
  const states = [];
  let calls = 0;
  const message = 'Import failed for MVDA. Check the ticker symbol.';
  const poll = createCompanySearch('MVDA', {
    getCompanies: async () => ({ companies: [] }),
    getStockQuote: async () => { calls++; throw pending(); },
    getCompany: async () => { throw Object.assign(new Error(message), { status: 409 }); },
    update: state => states.push(state),
  });
  assert.equal(await poll(() => true), true);
  assert.equal(await poll(() => true), false);
  assert.deepEqual(states, [{ importing: true }, { error: message }]);
});

test('saved company appears without another list search or quote request', async () => {
  const states = [];
  let searches = 0;
  let quotes = 0;
  const company = { ticker: 'AAPL', name: 'Apple' };
  const poll = createCompanySearch('aapl', {
    getCompanies: async () => { searches++; return { companies: [] }; },
    getStockQuote: async () => { quotes++; throw pending(); },
    getCompany: async (ticker, options) => {
      assert.equal(ticker, 'AAPL');
      assert.equal(options.cache, 'no-store');
      assert.ok(options.signal instanceof AbortSignal);
      return company;
    },
    update: state => states.push(state),
  });
  assert.equal(await poll(() => true), true);
  assert.equal(await poll(() => true), false);
  assert.equal(searches, 1);
  assert.equal(quotes, 1);
  assert.deepEqual(states.at(-1), { results: { type: 'companies', data: [company] } });
});

test('repeated timeouts cannot leave the UI claiming importing forever', async () => {
  const states = [];
  let time = 0;
  const poll = createCompanySearch('AAPL', {
    now: () => time,
    getCompanies: async () => ({ companies: [] }),
    getStockQuote: async () => { throw pending(); },
    getCompany: async () => { throw new DOMException('Timed out', 'TimeoutError'); },
    update: state => states.push(state),
  });
  assert.equal(await poll(() => true), true);
  time = 300000;
  assert.equal(await poll(() => true), false);
  assert.match(states.at(-1).error, /couldn’t confirm/);
});
