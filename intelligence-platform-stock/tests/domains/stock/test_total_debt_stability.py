"""Deterministic provider-source selection in the fundamental snapshot.

Regression coverage for the recurring ``total_debt`` (and other statement
field) drift between otherwise identical pulls of the same closed quarter.
The framework re-fetches BOTH FMP and SEC at analysis time; both emit the
same observation kinds (``financials`` / ``balance_sheet`` / ``cash_flow``),
so ``observations[0]`` used to decide the provider. FMP rows are
row-shaped (``{"total_debt": ...}``) while SEC XBRL rows are concept-shaped
(``{"concept": "total_debt", "value": ...}``), and the two providers define
"total debt" differently (FMP's combined ``totalDebt`` vs SEC's XBRL
``LongTermDebt`` component) — the raw ordering race flipped total_debt by
~2% between runs.

The snapshot builder now ranks providers deterministically, so the source
selection is a pure function of (row shape present, provider rank) and the
closed-period snapshot is byte-for-byte stable regardless of observation
insertion order.
"""

from datetime import datetime, timezone

from app.domains.stock.context_builder import StockContextBuilder
from app.shared.entities import EntityRef, Observation

AAPL = EntityRef(domain="stock", entity_type="company", entity_id="AAPL")


def _obs(kind: str, source: str, rows: list[dict]) -> Observation:
    return Observation(
        entity_ref=AAPL,
        observed_at=datetime.now(timezone.utc),
        data=rows,
        source=source,
        kind=kind,
    )


FMP_INCOME = _obs(
    "financials",
    "fmp",
    [
        {
            "period": "2026-06-27",
            "period_type": "quarterly",
            "revenue": 109417000000,
            "net_income": 29789000000,
            "gross_profit": 54770000000,
            "operating_income": 35695000000,
            "eps": 1.77,
        }
    ],
)


SEC_INCOME = _obs(
    "financials",
    "sec",
    [
        {"concept": "revenue", "value": 109417000000, "period": "Q3", "fiscal_year": 2026, "form": "10-Q", "filed": "2026-07-30", "unit": "USD", "source": "SEC"},
        {"concept": "net_income", "value": 29789000000, "period": "Q3", "fiscal_year": 2026, "form": "10-Q", "filed": "2026-07-30", "unit": "USD", "source": "SEC"},
        {"concept": "gross_profit", "value": 54770000000, "period": "Q3", "fiscal_year": 2026, "form": "10-Q", "filed": "2026-07-30", "unit": "USD", "source": "SEC"},
        {"concept": "operating_income", "value": 35695000000, "period": "Q3", "fiscal_year": 2026, "form": "10-Q", "filed": "2026-07-30", "unit": "USD", "source": "SEC"},
    ],
)


def _fmp_balance(total_debt: float = 84307000000) -> Observation:
    return _obs(
        "balance_sheet",
        "fmp",
        [
            {
                "period": "2026-06-27",
                "period_type": "quarterly",
                "total_assets": 383266000000,
                "total_liabilities": 275746000000,
                "total_debt": total_debt,
                "cash": 39544000000,
                "shareholders_equity": 107520000000,
            }
        ],
    )


def _sec_balance(combined_first: bool = False) -> Observation:
    combined = {
        "concept": "total_debt",
        "value": 84307000000,
        "period": "Q3",
        "fiscal_year": 2026,
        "form": "10-Q",
        "filed": "2026-07-30",
        "unit": "USD",
        "source": "SEC",
        "concept_alias": "DebtLongtermAndShorttermCombined",
    }
    long_term = {
        "concept": "total_debt",
        "value": 91688000000,
        "period": "Q3",
        "fiscal_year": 2026,
        "form": "10-Q",
        "filed": "2026-07-30",
        "unit": "USD",
        "source": "SEC",
        "concept_alias": "LongTermDebt",
    }
    pairs = [(combined, long_term)] if combined_first else [(long_term, combined)]

    rows = []
    for combined_row, long_row in pairs:
        rows.append(combined_row)
        rows.append(long_row)

    return _obs("balance_sheet", "sec", rows)


def _cashflow() -> Observation:
    return _obs(
        "cash_flow",
        "fmp",
        [
            {
                "period": "2026-06-27",
                "period_type": "quarterly",
                "operating_cash_flow": 31498000000,
                "free_cash_flow": 31914000000,
                "capital_expenditure": 6400000000,
            }
        ],
    )


def _build_snapshot(balances):
    return StockContextBuilder._build_fundamental_snapshot(
        financials=[FMP_INCOME, SEC_INCOME],
        balances=balances,
        cashflows=[_cashflow()],
        ratios=[],
    )


def test_total_debt_stable_regardless_of_observation_order():
    """FMP row-shaped data must win over SEC concept-shaped data in both
    insertion orders (the ordering race that previously flipped total_debt
    between identical pulls)."""

    fmp_first = _build_snapshot([_fmp_balance(), _sec_balance()])
    sec_first = _build_snapshot([_sec_balance(), _fmp_balance()])

    assert fmp_first["total_debt"] == 84307000000
    assert sec_first["total_debt"] == 84307000000

    assert fmp_first["total_debt"] == sec_first["total_debt"]
    assert fmp_first["cash"] == sec_first["cash"] == 39544000000

    # Provenance records which provider actually won.
    assert fmp_first["provenance"]["balance_sheet"]["source"] == "fmp"


def test_fmp_only_balance_unchanged():
    snap = _build_snapshot([_fmp_balance()])

    assert snap["total_debt"] == 84307000000
    assert snap["cash"] == 39544000000
    assert snap["provenance"]["balance_sheet"]["mode"] == "period_row"


def test_single_provider_income_unchanged():
    """Concept-shaped (SEC-only) input must still produce a coherent
    snapshot."""

    snap = StockContextBuilder._build_fundamental_snapshot(
        financials=[SEC_INCOME],
        balances=[_sec_balance(combined_first=True)],
        cashflows=[],
        ratios=[],
    )

    assert snap["revenue"] == 109417000000
    assert snap["net_income"] == 29789000000
    assert snap["total_debt"] == 84307000000
    assert snap["provenance"]["balance_sheet"]["mode"] == "concept_alignment"


def test_concept_alignment_combined_debt_line_item():
    """SEC emission (sec.py alias order) must supply the COMBINED debt
    concept; the builder then yields a total_debt consistent with FMP's
    combined ``totalDebt`` for the same quarter.

    Note: SECProvider.get_balance_sheet emits only the first matching alias
    per concept, so with the corrected alias order the builder only ever
    sees combined total_debt rows.
    """

    snap = StockContextBuilder._build_fundamental_snapshot(
        financials=[],
        balances=[_sec_balance(combined_first=True)],
        cashflows=[],
        ratios=[],
    )

    assert snap["total_debt"] == 84307000000


def test_aligned_concept_dedupe_prefers_usd_and_recent_filed():
    """Duplicate concept rows resolve to USD + most recently filed,
    independent of insertion order (deterministic snapshot)."""
    from app.domains.stock.context_builder import _aligned_concept_values

    base = {
        "concept": "cash",
        "period": "Q3",
        "fiscal_year": 2026,
        "form": "10-Q",
        "unit": "USD",
        "filed": "2026-07-01",
    }

    older = {**base, "value": 39544000000}
    newer = {**base, "value": 39700000000, "filed": "2026-07-30"}
    eur = {**base, "value": 36500000000, "unit": "EUR", "filed": "2026-07-30"}

    forward = _aligned_concept_values([older, newer, eur])
    backward = _aligned_concept_values([eur, newer, older])

    assert forward["cash"] == newer["value"]
    assert forward == backward


def test_provider_priority_unknown_source_is_last_resort():
    """Unknown providers rank below known canonical ones, and concept-shaped
    rows never outrank row-shaped rows."""

    unknown = _obs(
        "balance_sheet",
        "unknown",
        [
            {
                "period": "2026-06-27",
                "total_assets": 1,
                "total_liabilities": 1,
                "total_debt": 1,
                "cash": 1,
                "shareholders_equity": 1,
            }
        ],
    )

    fmp_first = _build_snapshot([_fmp_balance(), unknown])
    unknown_first = _build_snapshot([unknown, _fmp_balance()])

    assert fmp_first["total_debt"] == unknown_first["total_debt"] == 84307000000