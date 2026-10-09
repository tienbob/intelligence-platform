// Keep the displayed opportunity score tied to the analysis used by its link.
export function opportunityScore(opportunity) {
  if (opportunity.analysis_id && opportunity.analysis_status === 'completed'
      && Number.isFinite(opportunity.analysis_score)) {
    return opportunity.analysis_score;
  }
  return opportunity.score;
}
