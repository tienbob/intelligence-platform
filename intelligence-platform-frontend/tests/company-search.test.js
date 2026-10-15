import test from 'node:test';
import assert from 'node:assert/strict';
import { createCompanySearch } from '../src/services/companySearch.js';

const pending = () => Object.assign(new Error('AMD is not tracked yet; ingestion has started.'), { status: 404 });

test('pending import survives a gateway failure and automatically displays the company', async () => {
  const states = [];
  let calls = 0;
  const company = { ticker: 'AMD', name: 'Advanced Micro Devices' };
  const poll = createCompanySearch('AMD', {
    getCompanies: async () => {
      calls++;
      if (calls === 2) throw Object.assign(new Error('Gateway timeout'), { status: 504 });
      return { companies: calls === 3 ? [company] : [] };
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
