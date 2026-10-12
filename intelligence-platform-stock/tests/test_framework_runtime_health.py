"""Live health checks validate current results independently of old scores."""
import pytest
from scripts.gate3_equivalence import runtime_health_issues


def healthy():
    return dict(pipeline_status='completed', llm_success=True, overall_score=49,
                confidence=.8, recommendation='NEUTRAL', stages={'llm': 'success'})


def test_current_score_does_not_need_to_match_historical_score():
    assert runtime_health_issues(healthy()) == []


@pytest.mark.parametrize('field,value', [('overall_score', None), ('overall_score', float('nan')),
    ('overall_score', 101), ('confidence', -1), ('pipeline_status', 'failed'),
    ('llm_success', False), ('recommendation', ''), ('stages', {'llm': 'failed: timeout'})])
def test_runtime_failures_are_reported(field, value):
    snapshot = healthy()
    snapshot[field] = value
    assert runtime_health_issues(snapshot)
