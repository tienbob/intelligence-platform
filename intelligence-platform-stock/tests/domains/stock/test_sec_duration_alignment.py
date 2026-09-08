"""Duration-aware SEC concept selection in the fundamental snapshot.

Regression for the ~48% quarterly-revenue inflation: a Q2 10-Q group
(fiscal_year, fp, form) legitimately contains BOTH the ~3-month quarterly
fact and the ~6-month year-to-date fact for the same concept, with the same
``filed`` date. The selector used to keep one value per concept by
USD-then-latest-filed alone, so the YTD window could be surfaced as the
quarter's revenue (Q2 + Q1 reported as Q2).

Acceptance semantics asserted here (NOT a hardcoded revenue constant):

    target end = fiscal-period end (2026-06-30)
    selected duration ≈ 3 months for a 10-Q group
    selected duration ≈ 12 months for a 10-K group

Instant facts (balance sheet) carry no ``start`` and must be unaffected;
legacy rows without window metadata keep the original selection.
"""

from datetime import date, datetime, timezone

from app.domains.stock.context_builder import (
    StockContextBuilder,
    _aligned_concept_values,
    _fact_duration_days,
    _parse_date,
)
from app.shared.entities import EntityRef, Observation

TSLA = EntityRef(domain="stock", entity_type="company", entity_id="TSLA")

Q2_FILED = "2026-07-23"
Q1_FILED = "2026-04-24"

Q2_QUARTERLY_REVENUE = 28_236_000_000
Q2_YTD_REVENUE = 41_831_000_000
Q2_QUARTERLY_NET_INCOME = 1_067_000_000
Q2_YTD_NET_INCOME = 2_600_000_000
Q1_REVENUE = 13_595_000_000


def _obs(kind: str, source: str, rows: list[dict]) -> Observation:
    return Observation(
        entity_ref=TSLA,
        observed_at=datetime.now(timezone.utc),
        data=rows,
        source=source,
        kind=kind,
    )


def _sec_row(
    concept: str,
    value: int,
    start: str | None,
    end: str | None,
    *,
    form: str = "10-Q",
    fp: str = "Q2",
    filed: str = Q2_FILED,
    fy: int = 2026,
    unit: str = "USD",
) -> dict:
    return {
        "concept": concept,
        "value": value,
        "period": fp,
        "fiscal_year": fy,
        "form": form,
        "filed": filed,
        "start": start,
        "end": end,
        "unit": unit,
        "source": "SEC",
    }


def _q2_rows() -> list[dict]:
    """One Q2 10-Q group holding both windows, plus an older Q1 group.

    The YTD fact is listed FIRST: under the legacy USD-then-latest-filed
    rule (equal filed dates) the first candidate won, which is exactly how
    the YTD figure posed as the quarter.
    """
    return [
        _sec_row("revenue", Q2_YTD_REVENUE, "2026-01-01", "2026-06-30"),
        _sec_row("revenue", Q2_QUARTERLY_REVENUE, "2026-04-01", "2026-06-30"),
        _sec_row("net_income", Q2_YTD_NET_INCOME, "2026-01-01", "2026-06-30"),
        _sec_row("net_income", Q2_QUARTERLY_NET_INCOME, "2026-04-01", "2026-06-30"),
        _sec_row("revenue", Q1_REVENUE, "2026-01-01", "2026-03-31", fp="Q1", filed=Q1_FILED),
        _sec_row("net_income", 1_533_000_000, "2026-01-01", "2026-03-31", fp="Q1", filed=Q1_FILED),
    ]


def test_stale_earlier_ending_window_inside_same_group_is_rejected():
    # Hardening: even when a prior-period fact carries the group's own
    # fy/fp/form metadata (stale or mislabeled filing data), a window
    # ending before the group's target fiscal-period end must never win.
    rows = [
        _sec_row("revenue", Q2_YTD_REVENUE, "2026-01-01", "2026-06-30"),
        _sec_row("revenue", Q2_QUARTERLY_REVENUE, "2026-04-01", "2026-06-30"),
        _sec_row("revenue", Q1_REVENUE, "2026-01-01", "2026-03-31"),
    ]

    result = _aligned_concept_values(rows, duration_aware=True)

    assert result["revenue"] == Q2_QUARTERLY_REVENUE


def test_quarterly_window_selected_over_ytd_in_same_10q_group():
    result = _aligned_concept_values(_q2_rows(), duration_aware=True)

    assert result["revenue"] == Q2_QUARTERLY_REVENUE
    assert result["net_income"] == Q2_QUARTERLY_NET_INCOME
    assert result["period"] == "Q2"
    assert result["fiscal_year"] == 2026

    # Semantic acceptance criterion: the selected fact is the ~3-month
    # window ENDING at the fiscal-period end — not merely "a value that is
    # not the YTD constant".
    winner = next(
        row
        for row in _q2_rows()
        if row["concept"] == "revenue"
        and row["value"] == Q2_QUARTERLY_REVENUE
    )
    assert _parse_date(winner["end"]) == date(2026, 6, 30)
    assert _fact_duration_days(winner) == 90  # 2026-04-01 → 2026-06-30


def test_annual_filing_keeps_twelve_month_window():
    # A 10-K carries the 12-month FY duration AND the derived Q4 duration
    # under the same (fy, fp, form) group — "shortest globally" would pick
    # Q4 here, so the band must be derived from the filing shape.
    rows = [
        _sec_row(
            "revenue",
            29_500_000_000,
            "2026-10-01",
            "2026-12-31",
            form="10-K",
            fp="FY",
        ),
        _sec_row(
            "revenue",
            112_000_000_000,
            "2026-01-01",
            "2026-12-31",
            form="10-K",
            fp="FY",
        ),
    ]

    result = _aligned_concept_values(rows, duration_aware=True)

    assert result["revenue"] == 112_000_000_000
    winner = next(row for row in rows if row["value"] == result["revenue"])
    assert 300 <= _fact_duration_days(winner) <= 400


def test_instant_balance_facts_are_never_duration_filtered():
    rows = [
        _sec_row("total_assets", 137_806_000_000, None, "2026-06-30"),
        _sec_row("cash", 16_139_000_000, None, "2026-06-30"),
    ]

    duration_aware = _aligned_concept_values(rows, duration_aware=True)
    legacy = _aligned_concept_values(rows, duration_aware=False)

    assert duration_aware == legacy
    assert duration_aware["total_assets"] == 137_806_000_000
    assert duration_aware["cash"] == 16_139_000_000


def test_legacy_rows_without_window_metadata_keep_legacy_selection():
    # Pre-fix SEC rows (no start/end — the shape used by the existing
    # total_debt fixtures) must flow through unchanged.
    rows = [
        {
            "concept": "revenue",
            "value": 109_417_000_000,
            "period": "Q3",
            "fiscal_year": 2026,
            "form": "10-Q",
            "filed": "2026-07-30",
            "unit": "USD",
            "source": "SEC",
        },
        {
            "concept": "net_income",
            "value": 29_789_000_000,
            "period": "Q3",
            "fiscal_year": 2026,
            "form": "10-Q",
            "filed": "2026-07-30",
            "unit": "USD",
            "source": "SEC",
        },
    ]

    assert _aligned_concept_values(rows, duration_aware=True) == {
        "revenue": 109_417_000_000,
        "net_income": 29_789_000_000,
        "period": "Q3",
        "fiscal_year": 2026,
    }


def test_ytd_only_filing_falls_back_to_legacy_selection():
    # When no fact inside the expected band exists, selection keeps the
    # original deterministic rule instead of failing or inventing a value.
    rows = [_sec_row("revenue", Q2_YTD_REVENUE, "2026-01-01", "2026-06-30")]

    result = _aligned_concept_values(rows, duration_aware=True)

    assert result["revenue"] == Q2_YTD_REVENUE


def test_snapshot_builder_selects_quarterly_values_from_sec_fallback():
    financials = _obs("financials", "sec", _q2_rows())
    balances = _obs(
        "balance_sheet",
        "sec",
        [
            _sec_row("total_assets", 137_806_000_000, None, "2026-06-30"),
            _sec_row("shareholders_equity", 61_000_000_000, None, "2026-06-30"),
        ],
    )
    cashflows = _obs(
        "cash_flow",
        "sec",
        [
            _sec_row("operating_cash_flow", 3_100_000_000, "2026-04-01", "2026-06-30"),
            _sec_row("operating_cash_flow", 6_700_000_000, "2026-01-01", "2026-06-30"),
        ],
    )

    snap = StockContextBuilder._build_fundamental_snapshot(
        [financials],
        [balances],
        [cashflows],
        [],
    )

    assert snap["revenue"] == Q2_QUARTERLY_REVENUE
    assert snap["net_income"] == Q2_QUARTERLY_NET_INCOME
    assert snap["operating_cash_flow"] == 3_100_000_000
    assert snap["total_assets"] == 137_806_000_000

    # Margins recompute from the CORRECT scale now.
    assert snap["net_margin"] == round(
        Q2_QUARTERLY_NET_INCOME / Q2_QUARTERLY_REVENUE,
        4,
    )

    assert snap["provenance"]["income_statement"]["source"] == "sec"
    assert snap["provenance"]["balance_sheet"]["mode"] == "concept_alignment"