"""Regression coverage for the claim-validation false-positive gap.

Correct figures that exactly match the deterministic fundamental snapshot
(e.g. ``total_debt = 84,307,000,000``) were flagged "unsupported" merely
because no retrieved document happened to restate them in prose. The
numeric-assertion augmentation now cross-checks uncovered numbers against
the canonical snapshot and marks consistent figures ``supported`` (via
``canonical_snapshot``) so the narrative filter keeps correct sentences.
"""

from app.domains.stock.services.company_analysis import (
    _augment_claim_validation_with_numeric_assertions,
    _canonical_snapshot_match,
    _extract_numeric_assertions,
    _parse_assertion_amount,
)

SNAPSHOT = {
    "latest_statement": {
        "period": "2026-06-27",
        "period_type": "quarterly",
        "revenue": 109417000000,
        "net_income": 29789000000,
        "gross_profit": 54770000000,
        "operating_income": 35695000000,
        "total_assets": 383266000000,
        "total_debt": 84307000000,
        "cash": 39544000000,
        "shareholders_equity": 107520000000,
        "source": "FMP",
    },
    "free_cash_flow": 31914000000,
}


def test_parse_assertion_amount():
    assert _parse_assertion_amount("of $84.31 billion") == (84310000000.0, False)
    assert _parse_assertion_amount("at $31.91B") == (31910000000.0, False)
    assert _parse_assertion_amount("50.1%") == (50.1, True)
    assert _parse_assertion_amount("$1.2 trillion") == (1200000000000.0, False)
    assert _parse_assertion_amount("27.23 percent") == (27.23, False)
    assert _parse_assertion_amount("garbage") == (None, False)


def test_canonical_snapshot_match_user_reported_claims():
    """The exact two claims from the AAPL report that were wrongly flagged
    must now resolve against the canonical snapshot."""

    match = _canonical_snapshot_match(
        "Apple's total debt stood at $84.31 billion", SNAPSHOT
    )
    assert match is not None
    metric, value, period = match
    assert metric == "total_debt"
    assert value == 84307000000
    assert period == "2026-06-27"

    match = _canonical_snapshot_match(
        "Apple generated free cash flow of $31.91 billion", SNAPSHOT
    )
    assert match is not None
    assert match[0] == "free_cash_flow"
    assert match[1] == 31914000000


def test_canonical_snapshot_match_rejects_wrong_numbers():
    """Numbers that do NOT match any canonical value must stay unmatched."""

    assert (
        _canonical_snapshot_match("Apple's total debt stood at $12 billion", SNAPSHOT)
        is None
    )
    assert (
        _canonical_snapshot_match("revenue reached $999 billion", SNAPSHOT)
        is None
    )


def test_extraction_requires_known_prefix():
    assert "at $84.31 billion" in _extract_numeric_assertions(
        "Apple's total debt stood at $84.31 billion."
    )
    assert "of $31.91 billion" in _extract_numeric_assertions(
        "Apple generated free cash flow of $31.91 billion."
    )


def test_augmentation_marks_correct_numbers_supported():
    """Uncovered narrative numbers that match canonical data must NOT be
    marked unsupported (the false-positive gap)."""

    out = {
        "summary": (
            "Apple's total debt stood at $84.31 billion. "
            "Apple generated free cash flow of $31.91 billion."
        )
    }

    augmented = _augment_claim_validation_with_numeric_assertions(
        out,
        [],
        fundamental_snapshot=SNAPSHOT,
    )

    by_mode: dict[str, list[str]] = {}

    for item in augmented:
        by_mode.setdefault(item["validation_mode"], []).append(item["claim"])

    assert by_mode == {
        "canonical_snapshot": ["at $84.31 billion", "of $31.91 billion"]
    }

    assert all(
        item["status"] == "supported"
        for item in augmented
    )


def test_augmentation_still_flags_unverifiable_numbers():
    """Numbers that match NO canonical value remain unsupported so the
    narrative filter can strip the hosting sentence."""

    out = {"summary": "The market moved by $7 billion yesterday."}

    augmented = _augment_claim_validation_with_numeric_assertions(
        out,
        [],
        fundamental_snapshot=SNAPSHOT,
    )

    assert len(augmented) == 1
    assert augmented[0]["status"] == "unsupported"
    assert augmented[0]["validation_mode"] == "numeric_extraction"


def test_augmentation_preserves_existing_claim_validation():
    """Existing claim_validation entries pass through unchanged."""

    existing = [
        {
            "claim": "Revenue increased 12% year over year",
            "status": "supported",
            "evidence_status": "available",
            "validation_mode": "canonical_source",
        }
    ]

    out = {
        "summary": (
            "Revenue increased 12% year over year. "
            "Apple generated free cash flow of $31.91 billion."
        )
    }

    augmented = _augment_claim_validation_with_numeric_assertions(
        out,
        existing,
        fundamental_snapshot=SNAPSHOT,
    )

    assert augmented[0] == existing[0]
    assert augmented[1]["claim"] == "of $31.91 billion"
    assert augmented[1]["status"] == "supported"