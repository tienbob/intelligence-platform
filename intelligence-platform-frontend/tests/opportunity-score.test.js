import test from 'node:test';
import assert from 'node:assert/strict';
import { opportunityScore } from '../src/services/opportunityScore.js';

test('completed linked deep dive overrides a different screening score', () => {
  const row = { score: 48, analysis_id: 'aapl-analysis', analysis_status: 'completed', analysis_score: 49.06630533942941 };
  assert.equal(opportunityScore(row).toFixed(1), '49.1');
});

test('zero is a valid deep-dive score', () => {
  assert.equal(opportunityScore({ score: 48, analysis_id: 'analysis', analysis_status: 'completed', analysis_score: 0 }), 0);
});

test('screening remains available without a usable completed deep dive', () => {
  assert.equal(opportunityScore({ score: 48, analysis_score: 49 }), 48);
  assert.equal(opportunityScore({ score: 48, analysis_id: 'analysis', analysis_status: 'failed', analysis_score: 49 }), 48);
  assert.equal(opportunityScore({ score: 48, analysis_id: 'analysis', analysis_status: 'completed', analysis_score: null }), 48);
});
