export const scoreHelp = {
  investment: '0–100 research ranking. Higher means more attractive under our rules, not a predicted return.',
  risk: '0–100 risk measure. Higher means more concern. Read this separately from investment score.',
  confidence: 'Support from available scoring inputs, not your probability of making money.',
  overall: 'Combined confidence in this analysis, not a forecast of investment success.',
};

export function financialLimitations(data) {
  const financial = data?.data_quality?.financial_inputs;
  const messages = [];
  if (!financial) messages.push('Financial coverage is unavailable for this saved analysis.');
  else {
    const missing = Object.values(financial.missing_inputs || {}).some(fields => fields.length > 0);
    if (missing) messages.push('Financial data is incomplete. Review missing inputs before relying on the score.');
    if (financial.fallback_components?.length) messages.push('Some financial scores use a neutral fallback of 50 because inputs are missing.');
    if (financial.reporting_freshness < 1) messages.push('The financial reporting period is stale or unavailable.');
  }
  if (data?.analysis?.citation_warnings?.length) messages.push('Some AI statements have evidence warnings. Review their sources.');
  return messages;
}

export function opportunitySummary(opp) {
  const components = (opp.components || []).filter(c => c.label !== 'Risk' && Number.isFinite(c.value));
  const strongest = [...components].sort((a, b) => b.value - a.value)[0];
  return {
    reason: strongest ? `Strongest measured component: ${strongest.label} (${strongest.value.toFixed(0)}/100).` : 'Listed by the scoring model; no component breakdown is available.',
    concern: opp.risk_score == null ? 'Risk data is unavailable.' : `Measured risk: ${Number(opp.risk_score).toFixed(0)}/100. Higher means more concern.`,
  };
}
