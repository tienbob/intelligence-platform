import test from 'node:test';
import assert from 'node:assert/strict';
import { financialLimitations, opportunitySummary } from '../src/services/researchSummary.js';
import { readPreferences, preferenceKey, togglePreference } from '../src/services/companyPreferences.js';

test('missing and incomplete coverage remain distinct from complete coverage', () => {
  assert.match(financialLimitations({})[0], /unavailable/);
  const complete = { data_quality: { financial_inputs: { missing_inputs: {}, reporting_freshness: 1 } } };
  assert.deepEqual(financialLimitations(complete), []);
  complete.data_quality.financial_inputs.missing_inputs = { growth: ['revenue_growth'] };
  complete.data_quality.financial_inputs.fallback_components = ['growth'];
  assert.equal(financialLimitations(complete).length, 2);
});
test('risk cannot be described as a favorable component and zero is retained', () => {
  const summary = opportunitySummary({ risk_score: 0, components: [{ label: 'Risk', value: 99 }, { label: 'Growth', value: 0 }] });
  assert.match(summary.reason, /Growth \(0\/100\)/);
  assert.match(summary.concern, /0\/100/);
});
test('browser preferences are scoped to an account and tolerate corrupt storage', () => {
  const storage = { getItem: key => key === preferenceKey(1) ? '{"AAPL":{"watched":true,"hidden":false}}' : '{}' };
  assert.equal(readPreferences(storage, 1).AAPL.watched, true);
  assert.deepEqual(readPreferences(storage, 2), {});
  assert.deepEqual(readPreferences({ getItem: () => { throw Error('blocked'); } }, 1), {});
  assert.deepEqual(readPreferences({ getItem: () => 'null' }, 1), {});
  const prefs = togglePreference(readPreferences(storage, 1), 'AAPL', 'hidden');
  assert.equal(prefs.AAPL.hidden, true);
  assert.equal(prefs.AAPL.watched, true);
  assert.equal(togglePreference(prefs, 'AAPL', 'hidden').AAPL.hidden, false);
});
