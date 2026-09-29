"""Verify per-user ownership helpers (analyses + backtest_runs)."""

from app.core.security import get_actor, is_admin_actor, owns_row, visible_to_actor
from app.domains.stock.models.analysis import Analysis
from app.domains.stock.models.backtest import BacktestRun


class _H(dict):
    def get(self, k, d=None):
        return super().get(k, d)


class _R:
    def __init__(self, h):
        self.headers = h


def test_models_have_user_id():
    assert hasattr(Analysis, "user_id")
    assert hasattr(BacktestRun, "user_id")


def test_get_actor_parsing():
    assert get_actor(_R(_H({"X-User-Id": "2", "X-User-Role": "USER"}))) == {
        "user_id": 2,
        "role": "USER",
    }
    assert get_actor(_R(_H({}))) == {"user_id": None, "role": "SYSTEM"}
    assert get_actor(None) == {"user_id": None, "role": "SYSTEM"}
    # garbage user id -> anonymous, never crashes
    assert get_actor(_R(_H({"X-User-Id": "abc", "X-User-Role": "USER"}))) == {
        "user_id": None,
        "role": "USER",
    }


def test_visibility_rules():
    # regular user gets a SQL filter (not True)
    assert visible_to_actor(Analysis.user_id, {"user_id": 1, "role": "USER"}) is not True
    # admin / system / anonymous-dev see everything
    assert visible_to_actor(Analysis.user_id, {"user_id": 1, "role": "ADMIN"}) is True
    assert visible_to_actor(Analysis.user_id, None) is True


def test_owns_row():
    assert owns_row(1, {"user_id": 2, "role": "USER"}) is False
    assert owns_row(2, {"user_id": 2, "role": "USER"}) is True
    assert owns_row(None, {"user_id": 2, "role": "USER"}) is True  # system row
    assert owns_row(1, {"user_id": 2, "role": "ADMIN"}) is True
    assert is_admin_actor({"user_id": None, "role": "SYSTEM"}) is True
