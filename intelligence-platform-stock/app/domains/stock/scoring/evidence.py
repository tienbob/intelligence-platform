"""
Stock evidence attribution (Section 32, Section 50).

The generic claim↔source attribution mechanics live in
``app.intelligence.evidence``.

This module provides stock-specific resolution of LLM ``source`` blocks
against canonical stock facts.

IMPORTANT INTEGRITY RULE
------------------------

An LLM-supplied source block is a REFERENCE CANDIDATE, not proof.

A source block is accepted as a canonical fact reference only when:

    1. the requested entity matches the canonical analysis entity,
    2. the source type/provider is compatible with canonical provenance,
    3. the metric resolves to a canonical metric,
    4. the claimed period resolves to the same reporting period,
    5. the claimed value matches within the configured metric tolerance.

This module deliberately does NOT claim that a canonical fact is itself
final evidence.

The resolution pipeline is:

    LLM source block
        ↓
    StockEvidenceAttributor
        ↓
    Canonical fact resolution
        ↓
    EvidenceResolver / registry
        ↓
    Actual SEC/news/event evidence identity
        ↓
    ClaimValidator

``resolve_source_block()`` remains bool-compatible for existing callers.

``resolve_source_block_evidence()`` exposes the rich canonical resolution
object used for audit/evidence attribution.

``resolved_source_identity()`` returns a ``canonical_fact`` identity. It
does NOT manufacture an evidence ID from the canonical snapshot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Iterable
import math
import re

from app.core.logging import get_logger
from app.intelligence.evidence.attribution import EvidenceAttributor

logger = get_logger(__name__)

__all__ = [
    "EvidenceAttributor",
    "StockEvidenceAttributor",
    "SourceResolution",
    "parse_loose_number",
]


# ---------------------------------------------------------------------------
# Metric configuration
# ---------------------------------------------------------------------------

# Metrics stored as ratios in canonical snapshots. LLMs may report them as
# percentages, e.g. 27.23% vs 0.2723.
_RATIO_METRICS = {
    "revenue_growth",
    "revenue_growth_yoy",
    "earnings_growth",
    "fcf_growth",
    "gross_margin",
    "net_margin",
    "operating_margin",
    "fcf_yield",
    "roe",
    "roa",
}


# Metric aliases map presentation names onto canonical snapshot keys.
#
# Growth metrics intentionally remain explicit. ``revenue_growth`` is retained
# as a compatibility alias, but period validation still requires the source
# block to identify a compatible canonical period.
_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue_growth": (
        "revenue_growth",
        "revenue_growth_yoy",
    ),
    "revenue_growth_yoy": (
        "revenue_growth_yoy",
        "revenue_growth",
    ),
    "earnings_growth": ("earnings_growth",),
    "fcf_growth": ("fcf_growth",),
    "gross_margin": ("gross_margin",),
    "net_margin": ("net_margin",),
    "operating_margin": ("operating_margin",),
    "fcf_yield": ("fcf_yield",),
    "roe": ("roe",),
    "roa": ("roa",),
    "pe_ratio": ("pe_ratio",),
    "ps_ratio": ("ps_ratio",),
    "pb_ratio": ("pb_ratio",),
    "debt_to_equity": (
        "debt_to_equity",
        "debt_equity",
    ),
    "debt_equity": (
        "debt_equity",
        "debt_to_equity",
    ),
    "revenue": ("revenue",),
    "net_income": ("net_income",),
    "operating_income": ("operating_income",),
    "gross_profit": ("gross_profit",),
    "operating_cash_flow": ("operating_cash_flow",),
    "capital_expenditure": ("capital_expenditure",),
    "free_cash_flow": ("free_cash_flow",),
    "total_debt": ("total_debt",),
    "total_assets": ("total_assets",),
    "cash": ("cash",),
    "shareholders_equity": ("shareholders_equity",),
    "eps": ("eps",),
}


# Financial statement metrics are generally expected to be much closer to the
# canonical value than market-rounded values. Tolerances are intentionally
# conservative.
_METRIC_REL_TOLERANCE: dict[str, float] = {
    "revenue": 0.005,
    "net_income": 0.005,
    "operating_income": 0.005,
    "gross_profit": 0.005,
    "operating_cash_flow": 0.005,
    "capital_expenditure": 0.005,
    "free_cash_flow": 0.005,
    "total_debt": 0.005,
    "total_assets": 0.005,
    "cash": 0.005,
    "shareholders_equity": 0.005,
    "eps": 0.01,
    "revenue_growth": 0.005,
    "revenue_growth_yoy": 0.005,
    "earnings_growth": 0.005,
    "fcf_growth": 0.005,
    "gross_margin": 0.005,
    "net_margin": 0.005,
    "operating_margin": 0.005,
    "fcf_yield": 0.005,
    "roe": 0.005,
    "roa": 0.005,
    "pe_ratio": 0.01,
    "ps_ratio": 0.01,
    "pb_ratio": 0.01,
    "debt_to_equity": 0.01,
    "debt_equity": 0.01,
}


# Source types are normalized into canonical evidence classes.
_SOURCE_TYPE_ALIASES: dict[str, str] = {
    # Generic financial source labels.
    "financial": "financial_statement",
    "financial_statement": "financial_statement",
    "financials": "financial_statement",
    "statement": "financial_statement",

    # SEC-specific labels.
    "sec": "sec_filing",
    "sec_filing": "sec_filing",
    "sec_filing_statement": "sec_filing",

    # Useful compatibility aliases.
    "filing": "sec_filing",
}


# Providers which are compatible with the relevant canonical source class.
#
# This is intentionally conservative. A news provider cannot become SEC
# evidence merely because the numerical value happens to match.
#
# Values are normalized provider names (uppercase) as returned by
# ``_normalize_provider``.
_SOURCE_PROVIDER_COMPATIBILITY: dict[str, set[str]] = {
    "financial_statement": {
        "SEC",
        "SEC_EDGAR",
        "EDGAR",
        "FMP",
        "FINANCIAL_MODELING_PREP",
    },
    "sec_filing": {
        "SEC",
        "SEC_EDGAR",
        "EDGAR",
    },
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceResolution:
    """
    Result of resolving an LLM source block against canonical data.

    ``resolved`` means only that the source block successfully resolved to a
    canonical fact.

    It does NOT mean that final evidence has been independently resolved.

    ``location`` identifies the canonical snapshot field that matched.

    ``canonical_period`` is the exact canonical reporting period used by the
    resolver.

    ``metric`` is the normalized LLM metric.

    ``canonical_metric`` is the canonical metric key.

    ``evidence_type`` and ``provider`` identify the expected evidence class
    and provider.

    ``evidence_id`` is populated only when canonical provenance explicitly
    carries a real underlying evidence identifier. The resolver never invents
    one.
    """

    resolved: bool
    reason: str

    metric: str | None = None
    canonical_metric: str | None = None

    location: str | None = None

    canonical_value: float | None = None
    claimed_value: float | None = None

    canonical_period: Any = None
    claimed_period: Any = None

    canonical_fiscal_year: int | None = None
    canonical_fiscal_quarter: int | None = None

    claimed_fiscal_year: int | None = None
    claimed_fiscal_quarter: int | None = None

    period_type: str | None = None

    source_type: str | None = None
    source_name: str | None = None

    evidence_type: str | None = None
    provider: str | None = None

    company_id: str | None = None
    ticker: str | None = None

    evidence_id: str | int | None = None
    accession_number: str | None = None

    tolerance: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the resolution for diagnostics/audit metadata."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Parsing / period helpers
# ---------------------------------------------------------------------------


def parse_loose_number(
    value: Any,
) -> tuple[float | None, bool]:
    """
    Parse a loosely formatted number.

    Examples:

        "$96.22B"  -> (96220000000, False)
        "1.8%"     -> (1.8, True)
        "0.2552"   -> (0.2552, False)
        "59,688"   -> (59688, False)

    Returns:
        (number, was_percent)
    """
    if isinstance(value, bool):
        return None, False

    if isinstance(value, (int, float)):
        value_float = float(value)

        if not math.isfinite(value_float):
            return None, False

        return value_float, False

    if not isinstance(value, str):
        return None, False

    text = value.strip()

    if not text:
        return None, False

    was_percent = "%" in text

    normalized = (
        text.replace("$", "")
        .replace(",", "")
        .replace("%", "")
        .strip()
    )

    if not normalized:
        return None, False

    multiplier = 1.0

    suffix = normalized[-1].upper()

    if suffix in {"T", "B", "M", "K"}:
        multiplier = {
            "T": 1e12,
            "B": 1e9,
            "M": 1e6,
            "K": 1e3,
        }[suffix]

        normalized = normalized[:-1].strip()

    try:
        result = float(normalized) * multiplier
    except (TypeError, ValueError):
        return None, False

    if not math.isfinite(result):
        return None, False

    return result, was_percent


def _parse_date(value: Any) -> date | None:
    """Parse a provider/LLM date into a date object."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()

    if not text:
        return None

    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).date()
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue

    return None


def _quarter_from_date(value: date) -> int:
    """
    Return calendar quarter for a date.

    IMPORTANT:
    This helper is only a fallback for periods where fiscal metadata is not
    available. It must never override explicit fiscal-year/fiscal-quarter
    metadata from the canonical statement.
    """
    return ((value.month - 1) // 3) + 1


def _extract_fiscal_metadata(
    value: Any,
) -> tuple[int | None, int | None]:
    """
    Extract fiscal year / quarter from common period representations.

    Supported examples:

        "Q2 FY2027"
        "FY2027 Q2"
        "2027-Q2"
        {"fiscal_year": 2027, "fiscal_quarter": 2}
        {"year": 2027, "quarter": 2}
    """
    if value is None:
        return None, None

    if isinstance(value, dict):
        fiscal_year = value.get("fiscal_year")

        if fiscal_year is None:
            fiscal_year = value.get("fy")

        if fiscal_year is None:
            fiscal_year = value.get("year")

        fiscal_quarter = value.get("fiscal_quarter")

        if fiscal_quarter is None:
            fiscal_quarter = value.get("quarter")

        try:
            fiscal_year = (
                int(fiscal_year)
                if fiscal_year is not None
                else None
            )
        except (TypeError, ValueError):
            fiscal_year = None

        try:
            fiscal_quarter = (
                int(fiscal_quarter)
                if fiscal_quarter is not None
                else None
            )
        except (TypeError, ValueError):
            fiscal_quarter = None

        return fiscal_year, fiscal_quarter

    text = str(value).strip().upper()

    if not text:
        return None, None

    fiscal_year: int | None = None
    fiscal_quarter: int | None = None

    # Prefer explicit FY notation.
    fy_match = re.search(r"\bFY\s*(20\d{2}|19\d{2})\b", text)

    if fy_match:
        fiscal_year = int(fy_match.group(1))

    quarter_match = re.search(r"\bQ([1-4])\b", text)

    if quarter_match:
        fiscal_quarter = int(quarter_match.group(1))

    # Support 2027-Q2.
    if fiscal_year is None:
        year_quarter_match = re.search(
            r"\b(20\d{2}|19\d{2})\s*[-/]\s*Q([1-4])\b",
            text,
        )

        if year_quarter_match:
            fiscal_year = int(year_quarter_match.group(1))
            fiscal_quarter = int(year_quarter_match.group(2))

    return fiscal_year, fiscal_quarter


def _period_descriptor(value: Any) -> dict[str, Any]:
    """
    Normalize a period into structured fields.

    Examples:

        "2026-06-27"
            -> date=2026-06-27, year=2026, quarter=2

        "2026-Q2"
            -> year=2026, quarter=2

        "Q2 FY2027"
            -> fiscal_year=2027, fiscal_quarter=2

        "FY2027 Q2"
            -> fiscal_year=2027, fiscal_quarter=2

        {"period": "2026-07-26",
         "fiscal_year": 2027,
         "fiscal_quarter": 2}
            -> fiscal_year=2027, fiscal_quarter=2, date=2026-07-26
    """
    if value is None:
        return {}

    if isinstance(value, dict):
        raw = value.get("period", value.get("raw", value))

        text = str(raw).strip().upper()

        period_date = _parse_date(raw)

        fiscal_year, fiscal_quarter = _extract_fiscal_metadata(value)

        # If explicit fiscal metadata is absent, inspect the raw period text.
        text_fy, text_fq = _extract_fiscal_metadata(raw)

        if fiscal_year is None:
            fiscal_year = text_fy

        if fiscal_quarter is None:
            fiscal_quarter = text_fq

        year_match = re.search(
            r"\b(20\d{2}|19\d{2})\b",
            text,
        )

        year = (
            int(year_match.group(1))
            if year_match
            else None
        )

        quarter_match = re.search(
            r"\bQ([1-4])\b",
            text,
        )

        quarter = (
            int(quarter_match.group(1))
            if quarter_match
            else None
        )

        if period_date is not None:
            if year is None:
                year = period_date.year

            if quarter is None:
                quarter = _quarter_from_date(period_date)

        annual = bool(
            re.search(r"\bFY\b", text)
            and not quarter_match
        )

        if "ANNUAL" in text or "YEAR" in text:
            annual = True

        return {
            "raw": value,
            "text": text,
            "date": period_date,
            "year": year,
            "quarter": quarter,
            "fiscal_year": fiscal_year,
            "fiscal_quarter": fiscal_quarter,
            "annual": annual,
        }

    text = str(value).strip().upper()

    if not text:
        return {}

    period_date = _parse_date(value)

    year_match = re.search(
        r"\b(20\d{2}|19\d{2})\b",
        text,
    )

    year: int | None = (
        int(year_match.group(1))
        if year_match
        else None
    )

    quarter_match = re.search(
        r"\bQ([1-4])\b",
        text,
    )

    quarter: int | None = (
        int(quarter_match.group(1))
        if quarter_match
        else None
    )

    fiscal_year, fiscal_quarter = _extract_fiscal_metadata(value)

    if period_date is not None:
        if year is None:
            year = period_date.year

        if quarter is None:
            quarter = _quarter_from_date(period_date)

    annual = bool(
        re.search(r"\bFY\b", text)
        and not quarter_match
    )

    if "ANNUAL" in text or "YEAR" in text:
        annual = True

    return {
        "raw": value,
        "text": text,
        "date": period_date,
        "year": year,
        "quarter": quarter,
        "fiscal_year": fiscal_year,
        "fiscal_quarter": fiscal_quarter,
        "annual": annual,
    }


def _periods_match(
    claimed_period: Any,
    canonical_period: Any,
    *,
    canonical_period_type: Any = None,
    canonical_fiscal_year: int | None = None,
    canonical_fiscal_quarter: int | None = None,
) -> bool:
    """
    Compare financial periods semantically.

    Fiscal metadata has priority over calendar-quarter inference.

    Example:

        canonical:
            period = 2026-07-26
            fiscal_year = 2027
            fiscal_quarter = 2

        claimed:
            Q2 FY2027

    => True

    A dated claim is still required to match the exact canonical date when
    both sides provide explicit dates.

    Annual periods never cross-match quarterly periods.
    """
    if claimed_period is None or canonical_period is None:
        return False

    claimed = _period_descriptor(claimed_period)
    canonical = _period_descriptor(canonical_period)

    if not claimed or not canonical:
        return False

    canonical_type = (
        str(canonical_period_type).strip().lower()
        if canonical_period_type is not None
        else None
    )

    # --------------------------------------------------------------
    # Explicit canonical fiscal metadata
    # --------------------------------------------------------------

    if canonical_fiscal_year is not None:
        canonical["fiscal_year"] = int(canonical_fiscal_year)

    if canonical_fiscal_quarter is not None:
        canonical["fiscal_quarter"] = int(canonical_fiscal_quarter)

    # --------------------------------------------------------------
    # Exact date is strongest when BOTH sides provide one.
    # --------------------------------------------------------------

    claimed_date = claimed.get("date")
    canonical_date = canonical.get("date")

    if claimed_date is not None and canonical_date is not None:
        if claimed_date != canonical_date:
            return False

        # If dates match, continue checking explicit fiscal metadata when
        # supplied by either side. This catches contradictory FY/Q claims.
        claimed_fy = claimed.get("fiscal_year")
        canonical_fy = canonical.get("fiscal_year")

        if (
            claimed_fy is not None
            and canonical_fy is not None
            and claimed_fy != canonical_fy
        ):
            return False

        claimed_fq = claimed.get("fiscal_quarter")
        canonical_fq = canonical.get("fiscal_quarter")

        if (
            claimed_fq is not None
            and canonical_fq is not None
            and claimed_fq != canonical_fq
        ):
            return False

        return True

    # --------------------------------------------------------------
    # Annual vs quarterly must never cross-match.
    # --------------------------------------------------------------

    claimed_annual = bool(claimed.get("annual"))

    canonical_annual = bool(
        canonical.get("annual")
        or canonical_type == "annual"
    )

    if claimed_annual != canonical_annual:
        return False

    # --------------------------------------------------------------
    # Fiscal year / quarter matching.
    # --------------------------------------------------------------

    claimed_fy = claimed.get("fiscal_year")
    canonical_fy = canonical.get("fiscal_year")

    claimed_fq = claimed.get("fiscal_quarter")
    canonical_fq = canonical.get("fiscal_quarter")

    if canonical_fy is not None:
        if claimed_fy is None or claimed_fy != canonical_fy:
            return False

        if not canonical_annual and canonical_fq is not None:
            if claimed_fq is None or claimed_fq != canonical_fq:
                return False

        return True

    # --------------------------------------------------------------
    # Calendar year/quarter fallback.
    #
    # This is only used when explicit fiscal metadata is unavailable.
    # --------------------------------------------------------------

    claimed_year = claimed.get("year")
    canonical_year = canonical.get("year")

    if (
        claimed_year is None
        or canonical_year is None
        or claimed_year != canonical_year
    ):
        return False

    if canonical_annual:
        return True

    if (
        claimed_fq is not None
        and canonical.get("fiscal_quarter") is None
    ):
        canonical_quarter = canonical.get("quarter")

        if (
            canonical_quarter is None
            or claimed_fq != canonical_quarter
        ):
            return False

        return True

    claimed_quarter = claimed.get("quarter")
    canonical_quarter = canonical.get("quarter")

    if (
        claimed_quarter is not None
        and canonical_quarter is not None
    ):
        return claimed_quarter == canonical_quarter

    # A non-annual period without a quarter is ambiguous.
    return False


def _normalize_metric(metric: Any) -> str | None:
    """Normalize an LLM metric name."""
    if metric is None:
        return None

    normalized = (
        str(metric)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    return normalized or None


def _canonical_candidates(
    snapshot: dict[str, Any],
    aliases: tuple[str, ...],
) -> list[tuple[str, str, Any, dict[str, Any] | None]]:
    """
    Yield:

        (location, canonical_metric, value, provenance)

    candidates.

    ``provenance`` is optional and may contain:

        provider
        source
        evidence_id
        accession_number
        period
        fiscal_year
        fiscal_quarter

    Metrics are checked first because they contain explicitly exposed
    canonical metrics.

    Top-level snapshot values and latest_statement values remain supported for
    compatibility.
    """
    metrics = (
        snapshot.get("metrics")
        if isinstance(snapshot.get("metrics"), dict)
        else {}
    )

    latest = (
        snapshot.get("latest_statement")
        if isinstance(snapshot.get("latest_statement"), dict)
        else {}
    )

    candidates: list[
        tuple[str, str, Any, dict[str, Any] | None]
    ] = []

    for alias in aliases:
        if alias in metrics and metrics[alias] is not None:
            value = metrics[alias]

            provenance = (
                value
                if isinstance(value, dict)
                else None
            )

            if isinstance(value, dict):
                value = value.get("value")

            if value is not None:
                candidates.append(
                    (
                        f"metrics.{alias}",
                        alias,
                        value,
                        provenance,
                    )
                )

        if alias in snapshot and snapshot[alias] is not None:
            value = snapshot[alias]

            provenance = (
                value
                if isinstance(value, dict)
                else None
            )

            if isinstance(value, dict):
                value = value.get("value")

            if value is not None:
                candidates.append(
                    (
                        alias,
                        alias,
                        value,
                        provenance,
                    )
                )

        if alias in latest and latest[alias] is not None:
            value = latest[alias]

            provenance = (
                value
                if isinstance(value, dict)
                else None
            )

            if isinstance(value, dict):
                value = value.get("value")

            if value is not None:
                candidates.append(
                    (
                        f"latest_statement.{alias}",
                        alias,
                        value,
                        provenance,
                    )
                )

    return candidates


def _iter_mapping_strings(
    value: Any,
) -> Iterable[str]:
    """Yield normalized string values from a scalar/list/set-like field."""
    if value is None:
        return

    if isinstance(value, str):
        text = value.strip()

        if text:
            yield text.upper()

        return

    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            if item is None:
                continue

            text = str(item).strip()

            if text:
                yield text.upper()

        return

    text = str(value).strip()

    if text:
        yield text.upper()


def _normalize_source_type(value: Any) -> str | None:
    """Normalize source type text."""
    if value is None:
        return None

    return (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _normalize_provider(value: Any) -> str | None:
    """
    Normalize provider/source names.

    Examples:

        SEC
        sec_edgar
        EDGAR

    all normalize to ``SEC``.
    """
    if value is None:
        return None

    normalized = (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases = {
        "sec": "SEC",
        "sec_edgar": "SEC",
        "edgar": "SEC",
        "fmp": "FMP",
        "financial_modeling_prep": "FMP",
        "massive": "MASSIVE",
        "polygon": "MASSIVE",
    }

    return aliases.get(
        normalized,
        str(value).strip().upper(),
    )


def _canonical_source_type(value: Any) -> str | None:
    """Return the canonical evidence class for a source type."""
    normalized = _normalize_source_type(value)

    if normalized is None:
        return None

    return _SOURCE_TYPE_ALIASES.get(normalized)


# ---------------------------------------------------------------------------
# Attributor
# ---------------------------------------------------------------------------


class StockEvidenceAttributor(EvidenceAttributor):
    """
    Stock-specific source attribution.

    The attributor resolves LLM source candidates against the canonical
    fundamental snapshot belonging to the current analysis entity.

    It supports two levels:

        resolve_source_block()
            -> bool compatibility API

        resolve_source_block_evidence()
            -> rich SourceResolution for audit/evidence attachment

    IMPORTANT:

    Successful resolution means:

        "this LLM source block matches a canonical fact"

    It does NOT mean:

        "this is independently verified final evidence"

    Actual evidence identity must be resolved by the downstream
    EvidenceResolver / evidence registry.
    """

    def __init__(
        self,
        fundamental_snapshot: dict[str, Any] | None = None,
        *,
        ticker: str | None = None,
        company_id: str | int | None = None,
        default_source_type: str = "financial_statement",
        default_source_name: str | None = None,
        rel_tol: float = 0.005,
    ):
        super().__init__()

        self.fundamental_snapshot = (
            fundamental_snapshot
            if isinstance(fundamental_snapshot, dict)
            else {}
        )

        self.ticker = (
            str(ticker).upper()
            if ticker is not None
            else None
        )

        self.company_id = (
            str(company_id)
            if company_id is not None
            else None
        )

        normalized_type = _normalize_source_type(
            default_source_type
        )

        self.default_source_type = (
            normalized_type
            or "financial_statement"
        )

        self.default_source_name = (
            str(default_source_name).strip()
            if default_source_name
            else None
        )

        self.rel_tol = max(float(rel_tol), 0.0)

    # ------------------------------------------------------------------
    # Public resolution APIs
    # ------------------------------------------------------------------

    def resolve_source_block(
        self,
        source: Any,
    ) -> bool:
        """
        Bool-compatible source-block resolver.

        Returns True only when the source block resolves to canonical data.
        """
        resolution = self.resolve_source_block_evidence(source)

        return resolution.resolved

    def resolve_source_block_evidence(
        self,
        source: Any,
    ) -> SourceResolution:
        """
        Resolve an LLM source block against canonical stock data.

        This is the authoritative canonical-fact resolver.
        """
        if not isinstance(source, dict):
            return SourceResolution(
                resolved=False,
                reason="source_block_not_object",
            )

        metric = _normalize_metric(
            source.get("metric")
        )

        if not metric:
            return SourceResolution(
                resolved=False,
                reason="missing_metric",
            )

        aliases = _METRIC_ALIASES.get(metric)

        if not aliases:
            return SourceResolution(
                resolved=False,
                reason="unknown_metric",
                metric=metric,
            )

        claimed_raw = source.get("value")

        if claimed_raw is None:
            return SourceResolution(
                resolved=False,
                reason="missing_value",
                metric=metric,
            )

        claimed, was_percent = parse_loose_number(
            claimed_raw
        )

        if claimed is None:
            return SourceResolution(
                resolved=False,
                reason="non_numeric_value",
                metric=metric,
            )

        source_type_raw = (
            source.get("type")
            or source.get("source_type")
            or self.default_source_type
        )

        source_type = _canonical_source_type(
            source_type_raw
        )

        if source_type is None:
            return SourceResolution(
                resolved=False,
                reason="unsupported_source_type",
                metric=metric,
            )

        source_name_raw = (
            source.get("provider")
            or source.get("source")
            or source.get("source_name")
            or self.default_source_name
        )

        provider = _normalize_provider(
            source_name_raw
        )

        # Keep source_name compatibility with existing consumers.
        source_name = provider

        # --------------------------------------------------------------
        # Entity identity
        # --------------------------------------------------------------

        entity_resolution = self._validate_entity_identity(
            source
        )

        if not entity_resolution.resolved:
            return SourceResolution(
                resolved=False,
                reason=entity_resolution.reason,
                metric=metric,
                claimed_value=claimed,
                source_type=source_type,
                source_name=source_name,
                evidence_type=source_type,
                provider=provider,
                company_id=self.company_id,
                ticker=self.ticker,
            )

        # --------------------------------------------------------------
        # Source identity
        # --------------------------------------------------------------

        source_resolution = self._validate_source_identity(
            source_type=source_type,
            source_name=source_name,
        )

        if not source_resolution.resolved:
            return SourceResolution(
                resolved=False,
                reason=source_resolution.reason,
                metric=metric,
                claimed_value=claimed,
                source_type=source_type,
                source_name=source_name,
                evidence_type=source_type,
                provider=provider,
                company_id=self.company_id,
                ticker=self.ticker,
            )

        # --------------------------------------------------------------
        # Canonical latest statement
        # --------------------------------------------------------------

        latest_statement = self.fundamental_snapshot.get(
            "latest_statement"
        )

        if not isinstance(latest_statement, dict):
            return SourceResolution(
                resolved=False,
                reason="canonical_latest_statement_missing",
                metric=metric,
                claimed_value=claimed,
                source_type=source_type,
                source_name=source_name,
                evidence_type=source_type,
                provider=provider,
                company_id=self.company_id,
                ticker=self.ticker,
            )

        canonical_period = latest_statement.get(
            "period"
        )

        canonical_period_type = latest_statement.get(
            "period_type"
        )

        canonical_fiscal_year = self._first_int(
            latest_statement.get("fiscal_year"),
            latest_statement.get("fy"),
        )

        canonical_fiscal_quarter = self._first_int(
            latest_statement.get("fiscal_quarter"),
            latest_statement.get("fiscal_q"),
            latest_statement.get("quarter"),
        )

        # Some normalized snapshots may store fiscal metadata under a
        # nested period object.
        period_metadata = latest_statement.get("period_metadata")

        if isinstance(period_metadata, dict):
            canonical_fiscal_year = (
                canonical_fiscal_year
                if canonical_fiscal_year is not None
                else self._first_int(
                    period_metadata.get("fiscal_year"),
                    period_metadata.get("fy"),
                )
            )

            canonical_fiscal_quarter = (
                canonical_fiscal_quarter
                if canonical_fiscal_quarter is not None
                else self._first_int(
                    period_metadata.get("fiscal_quarter"),
                    period_metadata.get("quarter"),
                )
            )

        claimed_period = source.get("period")

        # A financial source block MUST specify its period.
        if claimed_period is None:
            return SourceResolution(
                resolved=False,
                reason="missing_period",
                metric=metric,
                claimed_value=claimed,
                canonical_period=canonical_period,
                source_type=source_type,
                source_name=source_name,
                evidence_type=source_type,
                provider=provider,
                company_id=self.company_id,
                ticker=self.ticker,
            )

        if not _periods_match(
            claimed_period,
            canonical_period,
            canonical_period_type=canonical_period_type,
            canonical_fiscal_year=canonical_fiscal_year,
            canonical_fiscal_quarter=canonical_fiscal_quarter,
        ):
            logger.debug(
                "Source block period mismatch: "
                "metric=%s claimed=%s canonical=%s "
                "canonical_fy=%s canonical_fq=%s",
                metric,
                claimed_period,
                canonical_period,
                canonical_fiscal_year,
                canonical_fiscal_quarter,
            )

            claimed_descriptor = _period_descriptor(
                claimed_period
            )

            return SourceResolution(
                resolved=False,
                reason="period_mismatch",
                metric=metric,
                claimed_value=claimed,
                claimed_period=claimed_period,
                canonical_period=canonical_period,
                canonical_fiscal_year=canonical_fiscal_year,
                canonical_fiscal_quarter=canonical_fiscal_quarter,
                claimed_fiscal_year=claimed_descriptor.get(
                    "fiscal_year"
                ),
                claimed_fiscal_quarter=claimed_descriptor.get(
                    "fiscal_quarter"
                ),
                period_type=(
                    str(canonical_period_type)
                    if canonical_period_type is not None
                    else None
                ),
                source_type=source_type,
                source_name=source_name,
                evidence_type=source_type,
                provider=provider,
                company_id=self.company_id,
                ticker=self.ticker,
            )

        # --------------------------------------------------------------
        # Canonical metric/value matching
        # --------------------------------------------------------------

        candidates = _canonical_candidates(
            self.fundamental_snapshot,
            aliases,
        )

        if not candidates:
            return SourceResolution(
                resolved=False,
                reason="canonical_metric_missing",
                metric=metric,
                claimed_value=claimed,
                claimed_period=claimed_period,
                canonical_period=canonical_period,
                canonical_fiscal_year=canonical_fiscal_year,
                canonical_fiscal_quarter=canonical_fiscal_quarter,
                source_type=source_type,
                source_name=source_name,
                evidence_type=source_type,
                provider=provider,
                company_id=self.company_id,
                ticker=self.ticker,
            )

        tolerance = _METRIC_REL_TOLERANCE.get(
            metric,
            self.rel_tol,
        )

        for (
            location,
            canonical_metric,
            canonical_raw,
            provenance,
        ) in candidates:
            canonical_num, canonical_was_percent = (
                parse_loose_number(canonical_raw)
            )

            if canonical_num is None:
                continue

            comparison_candidates = [claimed]

            # Canonical ratios are usually stored as 0..1 while an LLM often
            # supplies 27.23%. Support both representations.
            if (
                was_percent
                or canonical_was_percent
                or (
                    metric in _RATIO_METRICS
                    and abs(claimed) > 1.5
                )
            ):
                comparison_candidates.append(
                    claimed / 100.0
                )

            for candidate in comparison_candidates:
                if not self._numbers_match(
                    candidate,
                    canonical_num,
                    tolerance,
                ):
                    continue

                provenance_result = (
                    self._extract_provenance(
                        provenance=provenance,
                        latest_statement=latest_statement,
                        canonical_period=canonical_period,
                        canonical_fiscal_year=canonical_fiscal_year,
                        canonical_fiscal_quarter=canonical_fiscal_quarter,
                    )
                )

                logger.debug(
                    "Source block resolved: "
                    "metric=%s canonical_metric=%s "
                    "location=%s claimed=%s canonical=%s "
                    "period=%s fiscal_year=%s fiscal_quarter=%s",
                    metric,
                    canonical_metric,
                    location,
                    candidate,
                    canonical_num,
                    canonical_period,
                    canonical_fiscal_year,
                    canonical_fiscal_quarter,
                )

                return SourceResolution(
                    resolved=True,
                    reason="resolved",
                    metric=metric,
                    canonical_metric=canonical_metric,
                    location=location,
                    canonical_value=canonical_num,
                    claimed_value=candidate,
                    canonical_period=canonical_period,
                    claimed_period=claimed_period,
                    canonical_fiscal_year=canonical_fiscal_year,
                    canonical_fiscal_quarter=canonical_fiscal_quarter,
                    claimed_fiscal_year=(
                        _period_descriptor(
                            claimed_period
                        ).get("fiscal_year")
                    ),
                    claimed_fiscal_quarter=(
                        _period_descriptor(
                            claimed_period
                        ).get("fiscal_quarter")
                    ),
                    period_type=(
                        str(canonical_period_type)
                        if canonical_period_type is not None
                        else None
                    ),
                    source_type=source_type,
                    source_name=source_name,
                    evidence_type=(
                        provenance_result.get(
                            "evidence_type"
                        )
                        or source_type
                    ),
                    provider=(
                        provenance_result.get("provider")
                        or provider
                    ),
                    company_id=(
                        provenance_result.get(
                            "company_id"
                        )
                        or self.company_id
                    ),
                    ticker=self.ticker,
                    evidence_id=provenance_result.get(
                        "evidence_id"
                    ),
                    accession_number=provenance_result.get(
                        "accession_number"
                    ),
                    tolerance=tolerance,
                )

        return SourceResolution(
            resolved=False,
            reason="value_mismatch",
            metric=metric,
            claimed_value=claimed,
            claimed_period=claimed_period,
            canonical_period=canonical_period,
            canonical_fiscal_year=canonical_fiscal_year,
            canonical_fiscal_quarter=canonical_fiscal_quarter,
            source_type=source_type,
            source_name=source_name,
            evidence_type=source_type,
            provider=provider,
            company_id=self.company_id,
            ticker=self.ticker,
            tolerance=tolerance,
        )

    # ------------------------------------------------------------------
    # Identity validation
    # ------------------------------------------------------------------

    def _validate_entity_identity(
        self,
        source: dict[str, Any],
    ) -> SourceResolution:
        """
        Validate optional entity information in the source block.

        If the source block declares an entity, it must match the current
        analysis entity.

        If no entity metadata is declared, the source still resolves against
        the already-bound canonical snapshot for this attributor.
        """
        source_ticker = source.get("ticker")
        source_entity_id = source.get("entity_id")
        source_company_id = source.get("company_id")

        if self.ticker is not None:
            if source_ticker is not None:
                if (
                    str(source_ticker).strip().upper()
                    != self.ticker
                ):
                    return SourceResolution(
                        resolved=False,
                        reason="ticker_mismatch",
                    )

            if source_entity_id is not None:
                if (
                    str(source_entity_id).strip().upper()
                    != self.ticker
                ):
                    return SourceResolution(
                        resolved=False,
                        reason="entity_id_mismatch",
                    )

        if (
            self.company_id is not None
            and source_company_id is not None
            and str(source_company_id)
            != self.company_id
        ):
            return SourceResolution(
                resolved=False,
                reason="company_id_mismatch",
            )

        return SourceResolution(
            resolved=True,
            reason="entity_identity_valid",
        )

    def _validate_source_identity(
        self,
        *,
        source_type: str | None,
        source_name: str | None,
    ) -> SourceResolution:
        """
        Validate the declared source class/provider.

        An arbitrary provider name is not accepted merely because the number
        matches the canonical snapshot.

        If canonical provenance is known, the declared provider must match.

        If canonical provenance is unavailable, provider compatibility is
        checked against the source class.
        """
        normalized_type = _canonical_source_type(
            source_type
        )

        if normalized_type is None:
            return SourceResolution(
                resolved=False,
                reason="unsupported_source_type",
                source_type=source_type,
                source_name=source_name,
                evidence_type=source_type,
                provider=_normalize_provider(source_name),
            )

        provider = _normalize_provider(source_name)

        canonical_source = self._canonical_source_name()

        if canonical_source:
            canonical_provider = _normalize_provider(
                canonical_source
            )

            if (
                provider is None
                or canonical_provider is None
                or provider != canonical_provider
            ):
                return SourceResolution(
                    resolved=False,
                    reason="source_provider_mismatch",
                    source_type=normalized_type,
                    source_name=source_name,
                    evidence_type=normalized_type,
                    provider=provider,
                )

        else:
            # No explicit canonical provider. We still require the provider
            # to be compatible with the declared source class.
            if provider is None:
                return SourceResolution(
                    resolved=False,
                    reason="missing_source_provider",
                    source_type=normalized_type,
                    source_name=source_name,
                    evidence_type=normalized_type,
                    provider=None,
                )

            compatible_providers = (
                _SOURCE_PROVIDER_COMPATIBILITY.get(
                    normalized_type,
                    set(),
                )
            )

            if (
                compatible_providers
                and provider not in compatible_providers
            ):
                return SourceResolution(
                    resolved=False,
                    reason="source_provider_incompatible",
                    source_type=normalized_type,
                    source_name=source_name,
                    evidence_type=normalized_type,
                    provider=provider,
                )

        return SourceResolution(
            resolved=True,
            reason="source_identity_valid",
            source_type=normalized_type,
            source_name=provider,
            evidence_type=normalized_type,
            provider=provider,
        )

    def _canonical_source_name(self) -> str | None:
        """
        Return provider name recorded in canonical statement provenance.

        Supported fields:

            latest_statement.source
            latest_statement.provider
            latest_statement.source_name
        """
        latest_statement = self.fundamental_snapshot.get(
            "latest_statement"
        )

        if not isinstance(latest_statement, dict):
            return None

        for key in (
            "provider",
            "source",
            "source_name",
        ):
            source = latest_statement.get(key)

            if source is None:
                continue

            text = str(source).strip()

            if text:
                return text

        return None

    # ------------------------------------------------------------------
    # Provenance helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _first_int(
        *values: Any,
    ) -> int | None:
        """Return the first successfully parsed integer."""
        for value in values:
            if value is None:
                continue

            try:
                return int(value)
            except (TypeError, ValueError):
                continue

        return None

    @classmethod
    def _extract_provenance(
        cls,
        *,
        provenance: dict[str, Any] | None,
        latest_statement: dict[str, Any],
        canonical_period: Any,
        canonical_fiscal_year: int | None,
        canonical_fiscal_quarter: int | None,
    ) -> dict[str, Any]:
        """
        Extract underlying evidence provenance without inventing identity.

        Provenance can live on the metric itself or the latest statement.

        Recognized identifiers include:

            evidence_id
            source_evidence_id
            filing_id
            sec_filing_id
            accession_number
            accession
            company_id
            provider
            source
            evidence_type
            entity_type

        No ID is created if none exists.
        """
        result: dict[str, Any] = {}

        merged: dict[str, Any] = {}

        if isinstance(latest_statement, dict):
            merged.update(latest_statement)

        if isinstance(provenance, dict):
            merged.update(provenance)

        evidence_id = None

        for key in (
            "evidence_id",
            "source_evidence_id",
            "filing_id",
            "sec_filing_id",
        ):
            if merged.get(key) is not None:
                evidence_id = merged[key]
                break

        accession_number = None

        for key in (
            "accession_number",
            "accession",
            "sec_accession_number",
        ):
            if merged.get(key):
                accession_number = str(
                    merged[key]
                ).strip()
                break

        provider = _normalize_provider(
            merged.get("provider")
            or merged.get("source")
            or merged.get("source_name")
        )

        evidence_type = (
            _canonical_source_type(
                merged.get("evidence_type")
                or merged.get("entity_type")
                or merged.get("source_type")
            )
        )

        company_id = merged.get("company_id")

        result.update(
            {
                "evidence_id": evidence_id,
                "accession_number": accession_number,
                "provider": provider,
                "evidence_type": evidence_type,
                "company_id": (
                    str(company_id)
                    if company_id is not None
                    else None
                ),
                "period": canonical_period,
                "fiscal_year": canonical_fiscal_year,
                "fiscal_quarter": canonical_fiscal_quarter,
            }
        )

        return {
            key: value
            for key, value in result.items()
            if value is not None
        }

    # ------------------------------------------------------------------
    # Numeric helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _numbers_match(
        claimed: float,
        canonical: float,
        tolerance: float,
    ) -> bool:
        """
        Compare two numeric values safely.

        Handles zero explicitly so relative tolerance does not create an
        accidental divide-by-zero edge case.
        """
        if not (
            math.isfinite(claimed)
            and math.isfinite(canonical)
        ):
            return False

        if canonical == 0:
            return math.isclose(
                claimed,
                0.0,
                rel_tol=0.0,
                abs_tol=1e-9,
            )

        return math.isclose(
            claimed,
            canonical,
            rel_tol=max(tolerance, 0.0),
            abs_tol=1e-9,
        )

    # ------------------------------------------------------------------
    # Audit helpers
    # ------------------------------------------------------------------

    def resolved_source_identity(
        self,
        source: Any,
    ) -> dict[str, Any] | None:
        """
        Return a normalized canonical-fact identity.

        IMPORTANT:

        This method intentionally does NOT pretend that the canonical
        snapshot itself is final evidence.

        If an actual evidence ID is already present in canonical provenance,
        it is returned as a reference candidate. Otherwise no evidence ID is
        fabricated.

        Example output:

            {
                "kind": "canonical_fact",
                "entity_type": "company",
                "entity_id": "NVDA",
                "company_id": "3",
                "provider": "SEC",
                "evidence_type": "sec_filing",
                "metric": "revenue",
                "value": 96221000000,
                "period": "2026-07-26",
                "fiscal_year": 2027,
                "fiscal_quarter": 2,
                "location": "latest_statement.revenue",
            }

        The downstream EvidenceResolver must independently resolve any
        ``evidence_id`` against the evidence registry.
        """
        resolution = self.resolve_source_block_evidence(
            source
        )

        if not resolution.resolved:
            return None

        identity: dict[str, Any] = {
            "kind": "canonical_fact",
            "entity_type": "company",
            "entity_id": self.ticker,
            "company_id": (
                resolution.company_id
                or self.company_id
            ),
            "ticker": self.ticker,
            "evidence_type": resolution.evidence_type,
            "source_type": resolution.source_type,
            "provider": resolution.provider,
            "source_name": resolution.source_name,
            "metric": resolution.canonical_metric,
            "value": resolution.canonical_value,
            "period": resolution.canonical_period,
            "fiscal_year": resolution.canonical_fiscal_year,
            "fiscal_quarter": resolution.canonical_fiscal_quarter,
            "location": resolution.location,
            "tolerance": resolution.tolerance,
        }

        # These are optional and only appear if the canonical data actually
        # supplied them. Never fabricate them.
        if resolution.evidence_id is not None:
            identity["evidence_id"] = resolution.evidence_id

        if resolution.accession_number:
            identity["accession_number"] = (
                resolution.accession_number
            )

        return {
            key: value
            for key, value in identity.items()
            if value is not None
        }