"""Verify per-user ownership helpers (analyses + backtest_runs + alerts)."""

from app.core.security import get_actor, is_admin_actor, owns_row, visible_to_actor
from app.domains.stock.models.alert import Alert
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
    # Audit F1/S2: alerts are user-scoped too (migration 0018) — without this
    # any user could read and dismiss every other user's alerts.
    assert hasattr(Alert, "user_id")


def test_alert_visibility_and_ownership():
    # Regular user gets a SQL filter on Alert.user_id (not True) → own +
    # system rows only.
    assert visible_to_actor(Alert.user_id, {"user_id": 1, "role": "USER"}) is not True
    # System alert (NULL owner) is visible/readable by everyone.
    assert owns_row(None, {"user_id": 2, "role": "USER"}) is True
    # Another user's alert is not owned — mutating actions mirror the
    # analysis 404 (no existence leak).
    assert owns_row(1, {"user_id": 2, "role": "USER"}) is False
    # Admin bypass.
    assert owns_row(1, {"user_id": 2, "role": "ADMIN"}) is True


def test_alert_can_manage_gates_dismiss():
    from app.domains.stock.api.alerts import _can_manage

    owner = Alert(user_id=7, legacy_private=False, alert_type="price_alert",
                  severity="medium", message="m")
    system = Alert(user_id=None, legacy_private=False, alert_type="price_alert",
                   severity="medium", message="m")
    legacy = Alert(user_id=7, legacy_private=True, alert_type="price_alert",
                   severity="medium", message="m")
    user = {"user_id": 7, "role": "USER"}
    other = {"user_id": 8, "role": "USER"}
    admin = {"user_id": 8, "role": "ADMIN"}

    # Owner manages their own private alert; nobody else does.
    assert _can_manage(owner, user) is True
    assert _can_manage(legacy, other) is False   # another user's alert
    # Shared system rows are never manageable under the per-user receipt model.
    assert _can_manage(system, user) is False
    assert _can_manage(system, admin) is False
    # An owner of a grandfathered legacy-private row still cannot mutate it:
    # its old is_read writes were shared writes, so the row is view-only.
    assert _can_manage(legacy, user) is False


def test_get_actor_parsing():
    assert get_actor(_R(_H({"X-User-Id": "2", "X-User-Role": "USER"}))) == {
        "user_id": 2,
        "role": "USER",
    }
    # Missing role must never become SYSTEM/admin-equivalent (audit S01) —
    # an identity-less request falls back to the least-privileged role.
    assert get_actor(_R(_H({}))) == {"user_id": None, "role": "USER"}
    assert get_actor(None) == {"user_id": None, "role": "USER"}
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
