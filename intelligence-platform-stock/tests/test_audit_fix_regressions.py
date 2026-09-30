"""Regression coverage for the 2026-09-30 audit fixes.

Locks the behaviours that were previously broken/misleading so they cannot
silently regress:
- F01 unknown-ticker auto-ingest imports a real module
- F03 alert read state + ownership are exposed to the feed
- F07 zero/missing values are preserved (never fabricated)
- S02 metrics labels carry no resource identifiers
"""
import ast
import asyncio
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from starlette.requests import Request

API_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "domains" / "stock" / "api"


def user_request(user_id: str = "7", role: str = "USER"):
    return Request({
        "type": "http",
        "headers": [(b"x-user-id", user_id.encode()), (b"x-user-role", role.encode())],
        "method": "GET",
        "path": "/",
    })


# ── F01: auto-ingest imports resolve ─────────────────────────────


def test_unknown_ticker_auto_ingest_imports_exist():
    """Both lazy-ingestion paths must import the module that actually exists."""
    for filename in ("companies.py", "financials.py"):
        tree = ast.parse((API_DIR / filename).read_text())
        modules = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        assert "app.domains.stock.api.stocks" in modules, filename
        assert not [m for m in modules if m.startswith("app.domains.stock.api.v1")], filename
    # the target module is on disk (the old api/v1/ package never was)
    assert (API_DIR / "stocks.py").exists()
    assert not (API_DIR / "v1").exists()


# ── F03: alert read state + ownership ────────────────────────────


def test_list_alerts_reports_read_state_and_ownership():
    from app.domains.stock.api import alerts as alerts_api
    from app.domains.stock.models.alert import Alert

    mine = Alert(id=1, user_id=7, legacy_private=False, alert_type="price_alert",
                 severity="medium", message="mine", is_read=False)
    system = Alert(id=2, user_id=None, legacy_private=False, alert_type="price_alert",
                   severity="medium", message="system", is_read=True)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        all=lambda: [(mine, "AAPL", False), (system, None, True)]
    )

    response = asyncio.run(
        alerts_api.list_alerts(user_request(), unread_only=False, limit=50, offset=0, db=db)
    )

    assert [a.id for a in response.alerts] == [1, 2]
    assert response.alerts[0].is_read is False
    assert response.alerts[0].can_manage is True   # own row
    assert response.alerts[1].is_read is True      # per-user receipt state
    assert response.alerts[1].can_manage is False  # shared rows are view-only


def test_mark_alert_read_rejects_other_users_row():
    from fastapi import HTTPException

    from app.domains.stock.api import alerts as alerts_api
    from app.domains.stock.models.alert import Alert

    other = Alert(id=5, user_id=99, alert_type="price_alert", severity="medium", message="theirs")
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(one_or_none=lambda: (other, "AAPL"))

    try:
        asyncio.run(alerts_api.mark_alert_read(5, user_request(), db=db))
    except HTTPException as exc:
        assert exc.status_code == 404          # no existence leak
    else:  # pragma: no cover - the call must not succeed
        raise AssertionError("cross-user dismiss must be rejected")


# ── F07: zero versus missing ─────────────────────────────────────


def test_opportunity_schema_preserves_zero_and_missing():
    from app.domains.stock.schemas.analysis import InvestmentOpportunity, ScoreComponent

    missing = InvestmentOpportunity(ticker="AAPL", score=20.0)
    assert missing.risk_score is None          # missing stays missing
    assert missing.analysis_score is None
    assert ScoreComponent(label="Risk", weight=0.15).value is None

    genuine_zero = InvestmentOpportunity(ticker="MSFT", score=0.0, risk_score=0)
    assert genuine_zero.risk_score == 0        # a real zero is not "missing"


# ── S02: metrics labels ──────────────────────────────────────────


def test_metrics_labels_are_route_templates():
    from app.core.observability import normalize_endpoint

    assert normalize_endpoint(
        "/api/v1/analysis/9f1c8e2a-1111-2222-3333-444455556666"
    ) == "/api/v1/analysis/{id}"
    assert normalize_endpoint("/api/v1/backtest/runs/42/trades") == "/api/v1/backtest/runs/{id}/trades"
    assert normalize_endpoint("/api/v1/stocks/AAPL") == "/api/v1/stocks/AAPL"


# ── F04: idempotency namespacing + replay shape ──────────────────


def _idempotency_request(user_id: str, body: bytes, path: str = "/api/v1/analysis/company"):
    raw_headers = [
        (b"x-user-id", user_id.encode()),
        (b"x-user-role", b"USER"),
        (b"idempotency-key", b"key-123"),
        (b"content-type", b"application/json"),
    ]

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http",
        "headers": raw_headers,
        "method": "POST",
        "path": path,
        "query_string": b"",
        "root_path": "",
        # starlette needs server/client for Request.url / request.body()
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "scheme": "http",
        "http_version": "1.1",
    }, receive)


def test_idempotency_key_is_namespaced_by_actor_route_and_body():
    from app.core import security as sec

    sec._idempotency_store.clear()
    body = b'{"ticker": "AAPL"}'

    # Same key + same body + same user → identical namespaced storage key.
    key1 = asyncio.run(sec.check_idempotency(_idempotency_request("1", body)))
    key2 = asyncio.run(sec.check_idempotency(_idempotency_request("1", body)))
    assert key1 == key2

    # The reproduced cross-user leak: another user with the same raw key and
    # body must get a DIFFERENT storage key.
    other_user = asyncio.run(sec.check_idempotency(_idempotency_request("2", body)))
    assert other_user != key1

    # A changed body is a new request.
    changed_body = asyncio.run(sec.check_idempotency(_idempotency_request("1", b'{"ticker": "MSFT"}')))
    assert changed_body != key1

    # A different route cannot collide.
    other_route = asyncio.run(
        sec.check_idempotency(_idempotency_request("1", body, path="/api/v1/portfolio/optimize"))
    )
    assert other_route != key1


def test_idempotency_replay_returns_original_status_and_payload():
    from app.core import security as sec

    sec._idempotency_store.clear()
    body = b'{"ticker": "AAPL"}'
    key = asyncio.run(sec.check_idempotency(_idempotency_request("1", body)))
    sec.store_idempotency_result(key, 202, {"analysis_id": "abc", "status": "queued"})

    try:
        asyncio.run(sec.check_idempotency(_idempotency_request("1", body)))
    except sec.IdempotencyReplay as replay:
        # Original 202 + payload (NOT an error envelope) and the raw key.
        assert replay.status_code == 202
        assert replay.body == {"analysis_id": "abc", "status": "queued"}
        assert replay.key == "key-123"
    else:  # pragma: no cover - the replay must be detected
        raise AssertionError("replay was not detected")


# ── F12: snapshot coverage is disclosed, never overstated ────────


def test_snapshot_coverage_reports_unpinned_runs():
    from app.domains.stock.scoring.backtest import compute_snapshot_coverage

    report = compute_snapshot_coverage(snapshot=None, strategy="momentum")
    assert report["mode"] == "unpinned"
    assert "prices" in report["live"]
    assert report["pinned"] == []
    assert report["snapshot_id"] is None


def test_snapshot_coverage_marks_score_driven_runs_partially_pinned():
    from datetime import datetime, timezone

    from app.domains.stock.models.backtest import BacktestSnapshot
    from app.domains.stock.scoring.backtest import compute_snapshot_coverage

    snapshot = BacktestSnapshot(
        id=3, name="s", as_of=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    # Prices + benchmark pinned, but score history is still live (F12 core).
    report = compute_snapshot_coverage(
        snapshot=snapshot, strategy="score_threshold", benchmark_source="snapshot"
    )
    assert report["mode"] == "partially_pinned"
    assert report["snapshot_id"] == 3
    assert set(report["pinned"]) == {"prices", "benchmark"}
    assert report["live"] == ["score_history"]

    # Price-only strategies on the same snapshot really are fully pinned.
    pinned = compute_snapshot_coverage(
        snapshot=snapshot, strategy="momentum", benchmark_source="snapshot"
    )
    assert pinned["mode"] == "pinned"
    assert pinned["live"] == []


def test_snapshot_coverage_records_live_benchmark_fallback():
    from datetime import datetime, timezone

    from app.domains.stock.models.backtest import BacktestSnapshot
    from app.domains.stock.scoring.backtest import compute_snapshot_coverage

    snapshot = BacktestSnapshot(
        id=4, name="s", as_of=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    # Benchmark ticker missing from the snapshot → live fallback disclosed.
    report = compute_snapshot_coverage(
        snapshot=snapshot, strategy="momentum", benchmark_source="live"
    )
    assert report["mode"] == "partially_pinned"
    assert report["live"] == ["benchmark"]

    # No benchmark computed at all → listed in neither bucket.
    none_report = compute_snapshot_coverage(
        snapshot=snapshot, strategy="momentum", benchmark_source="none"
    )
    assert none_report["mode"] == "pinned"
    assert none_report["live"] == []


# ── S03: the rate limiter is wired, scoped and returns 429 + Retry-After ──


def test_rate_limit_middleware_matches_paid_work_paths_only():
    from app.core.rate_limit_middleware import limited_scope_for

    assert limited_scope_for("POST", "/internal/analysis/company") is not None
    assert limited_scope_for("POST", "/api/v1/stock/analysis/company") is not None
    assert limited_scope_for("POST", "/api/v1/portfolio/optimize") is not None
    # GETs and unrelated POSTs are not throttled by this middleware.
    assert limited_scope_for("GET", "/internal/analysis/company") is None
    assert limited_scope_for("POST", "/api/v1/stock/alerts/") is None


def test_rate_limit_enforced_over_quota_429_with_retry_after(monkeypatch):
    import uuid

    import pytest
    from fastapi import HTTPException

    from app.core import rate_limit as rl

    monkeypatch.setattr(rl.settings, "RATE_LIMIT_ENABLED", True)
    key = f"test-{uuid.uuid4()}"

    async def run():
        await rl.rate_limiter.check(key, limit=2)
        await rl.rate_limiter.check(key, limit=2)
        with pytest.raises(HTTPException) as exc:
            await rl.rate_limiter.check(key, limit=2)
        assert exc.value.status_code == 429
        assert "Retry-After" in (exc.value.headers or {})

    asyncio.run(run())


def test_rate_limit_disabled_flag_allows_unlimited(monkeypatch):
    from app.core import rate_limit as rl

    monkeypatch.setattr(rl.settings, "RATE_LIMIT_ENABLED", False)
    key = "disabled-flag-check"

    async def run():
        for _ in range(50):
            await rl.rate_limiter.check(key, limit=1)

    asyncio.run(run())


def test_client_key_prefers_gateway_forwarded_user(monkeypatch):
    from app.core.rate_limit import settings
    monkeypatch.setattr(settings, "INTERNAL_SERVICE_KEY", "test-service-key")
    from app.core.rate_limit import get_client_key

    with_user = Request({
        "type": "http",
        "headers": [(b"x-user-id", b"42"), (b"x-service-key", b"test-service-key")],
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "client": ("10.0.0.5", 1234),
    })
    assert get_client_key(with_user) == "user:42"

    anonymous = Request({
        "type": "http",
        "headers": [],
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "client": ("10.0.0.5", 1234),
    })
    assert get_client_key(anonymous) == "10.0.0.5"
