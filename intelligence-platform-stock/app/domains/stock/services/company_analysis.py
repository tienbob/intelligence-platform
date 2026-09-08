"""
Company analysis canonical persistence core.

ONE canonical writer for the persisted `analyses` contract (scores,
source-backed claim rows, snapshot columns, provenance).

Analysis EXECUTION belongs to the framework path:

    api/analysis.py / workers/analysis_worker.py
        → execute_company_analysis()
        → IntelligencePipeline
        → persist_analysis()

Legacy orchestration was removed in Gate 6.

Canonical contract: docs/PLAN_ANALYSIS_CONTRACT.md
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.stock.models.analysis import Analysis, AnalysisSource
from app.domains.stock.models.company import Company


ANALYSIS_VERSION = "1.0"

StageCallback = Any


@dataclass
class AnalysisExecutionResult:
    """Everything the execution produced; wrappers decide what to expose."""

    analysis: Analysis
    score: Any
    llm_output: dict[str, Any]
    context: dict[str, Any]
    evidence_package: dict[str, Any]


def _safe_float(value: Any) -> float | None:
    """Coerce an LLM-supplied numeric-ish value to float."""

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    try:
        return float(
            str(value)
            .replace(",", "")
            .replace("$", "")
            .replace("%", "")
        )
    except (ValueError, TypeError):
        return None


def _score_as_snapshot(score: Any) -> dict[str, Any]:
    """
    Serialize the deterministic score into a portable, JSON-safe snapshot.

    This is the ONLY authoritative scoring record for an analysis. API
    consumers must read the recommendation block from this snapshot rather
    than from the company's latest ``InvestmentScore`` row: a later
    ``recalculate_scores()`` run or another analysis writes a new row, which
    previously made the response's ``recommendation`` drift away from the
    top-level ``investment_score``/``risk_score`` (the split-brain defect
    observed in AAPL/NVDA payloads).
    """
    recommendation = (
        getattr(score, "recommendation", None)
        or "HOLD"
    )

    values = {
        "overall_score": getattr(score, "overall_score", None),
        "risk_score": getattr(score, "risk_score", None),
        "confidence": getattr(score, "confidence", None),
        "recommendation": recommendation,
        "fundamental_score": getattr(score, "fundamental_score", None),
        "valuation_score": getattr(score, "valuation_score", None),
        "growth_score": getattr(score, "growth_score", None),
        "technical_score": getattr(score, "technical_score", None),
        "sentiment_score": getattr(score, "sentiment_score", None),
        "catalyst_score": getattr(score, "catalyst_score", None),
        "scoring_model": getattr(score, "scoring_model", None),
        "scoring_version": getattr(score, "scoring_version", None),
        "scoring_weights": getattr(score, "scoring_weights", None),
        "data_quality_score": getattr(score, "data_quality_score", None),
        "score_source": "deterministic_scoring",
    }

    timestamp = getattr(score, "timestamp", None)

    if timestamp is not None:
        values["timestamp"] = timestamp.isoformat()

    return values


def _sanitize_llm_recommendation(
    raw_llm_output: dict[str, Any],
    score: Any,
) -> dict[str, Any]:
    """
    Remove LLM-generated scoring/recommendation verdicts.

    The deterministic scoring engine is the only authoritative source of the
    investment score, recommendation label, and confidence.  LLM output may
    still contain legacy fields from earlier prompt versions; strip them so
    downstream consumers never see two disagreeing engines in one payload.
    """
    cleaned = {
        key: value
        for key, value in raw_llm_output.items()
        if key not in {
            "recommendation",
            "recommendation_details",
            "investment_score",
            "recommended_weight",
        }
    }

    deterministic_recommendation = (
        getattr(score, "recommendation", None)
        or "HOLD"
    )

    cleaned["recommendation_details"] = {
        "score": getattr(score, "overall_score", None),
        "confidence": getattr(score, "confidence", None),
        "recommendation": deterministic_recommendation,
        "score_source": "deterministic_scoring",
        "note": (
            "This recommendation is produced by the deterministic scoring "
            "engine and is authoritative. Any LLM-generated verdict has been "
            "removed."
        ),
    }

    return cleaned


def _reco_bucket(label: Any) -> str:
    """Normalize recommendation labels to buy/neutral/sell."""

    value = str(label or "").upper()

    if "BUY" in value:
        return "buy"

    if "SELL" in value:
        return "sell"

    return "neutral"


# ---------------------------------------------------------------------------
# Narrative hard gate
# ---------------------------------------------------------------------------

_NARRATIVE_TEXT_FIELDS = (
    "summary",
    "market_interpretation",
    "investment_thesis",
)

_NARRATIVE_LIST_FIELDS = (
    "bull_case",
    "bear_case",
    "catalysts",
    "risks",
    "invalidating_conditions",
    "causes",
)

# List fields whose items are dicts: the key inside each dict that holds
# the prose to filter (e.g. {"cause": "...", "impact": "high"}).
_NARRATIVE_DICT_ITEM_TEXT_KEYS = {
    "causes": "cause",
}

_NARRATIVE_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "has",
        "have",
        "was",
        "were",
        "its",
        "their",
        "are",
        "not",
        "but",
        "also",
        "than",
        "then",
        "into",
        "over",
        "after",
        "before",
        "while",
        "about",
        "which",
        "would",
        "could",
        "should",
        "been",
        "being",
        "more",
        "most",
        "due",
        "ahead",
        "amid",
        "among",
        "along",
        "such",
        "these",
        "those",
    }
)

_NARRATIVE_MATCH_RATIO = 0.6
_NARRATIVE_MIN_TOKENS = 3

_WITHHELD_SUMMARY = (
    "Summary withheld: the generated narrative contained claims that "
    "could not be verified against retrieved evidence. See "
    "claim_validation for the full audit trail."
)


def _claim_tokens(text: Any) -> list[str]:
    """Return informative lowercase tokens."""

    return [
        token
        for token in re.findall(
            r"[a-z0-9]+",
            str(text or "").lower(),
        )
        if len(token) > 2 and token not in _NARRATIVE_STOPWORDS
    ]


def _matched_claim(
    sentence: str,
    claim_token_lists: list[tuple[list[str], str]],
) -> str | None:
    """
    Return the unsupported claim this sentence asserts, if any.

    A claim must have at least `_NARRATIVE_MIN_TOKENS` informative tokens
    and reach `_NARRATIVE_MATCH_RATIO` overlap with the sentence.
    """

    sentence_tokens = set(_claim_tokens(sentence))

    if not sentence_tokens:
        return None

    for claim_tokens, claim_text in claim_token_lists:
        if len(claim_tokens) < _NARRATIVE_MIN_TOKENS:
            continue

        overlap = sum(
            1
            for token in claim_tokens
            if token in sentence_tokens
        )

        if overlap / len(claim_tokens) >= _NARRATIVE_MATCH_RATIO:
            return claim_text

    return None


def strip_unsupported_from_narrative(
    llm_output: dict[str, Any],
    claim_validation: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """
    Remove unsupported/conflicting claim assertions from the narrative.

    The original claim_validation audit trail is preserved.

    Only claims explicitly marked `supported` are allowed to drive
    the verified narrative surface.
    """

    unsupported = [
        item.get("claim", "")
        for item in claim_validation
        if isinstance(item, dict)
        and item.get("status") != "supported"
    ]

    unsupported = [
        claim for claim in unsupported if claim
    ]

    if not unsupported:
        return llm_output, None

    claim_token_lists = [
        (_claim_tokens(claim), claim)
        for claim in unsupported
    ]

    filtered = dict(llm_output)

    removed: list[dict[str, str]] = []
    fields: set[str] = set()

    # Text fields -----------------------------------------------------------

    for field in _NARRATIVE_TEXT_FIELDS:
        text = filtered.get(field)

        if not isinstance(text, str) or not text.strip():
            continue

        sentences = re.split(
            r"(?<=[.!?])\s+",
            text.strip(),
        )

        kept: list[str] = []

        for sentence in sentences:
            claim = _matched_claim(
                sentence,
                claim_token_lists,
            )

            if claim:
                removed.append(
                    {
                        "field": field,
                        "text": sentence.strip(),
                        "claim": claim,
                    }
                )
                fields.add(field)
            else:
                kept.append(sentence)

        if field in fields:
            new_text = " ".join(
                part.strip()
                for part in kept
                if part.strip()
            )

            if not new_text and field == "summary":
                new_text = _WITHHELD_SUMMARY

            filtered[field] = new_text

    # List fields -----------------------------------------------------------

    for field in _NARRATIVE_LIST_FIELDS:
        items = filtered.get(field)

        if not isinstance(items, list):
            continue

        # Dict-item fields (e.g. causes) declare the prose key.
        prose_key = _NARRATIVE_DICT_ITEM_TEXT_KEYS.get(field)

        kept_items: list[Any] = []

        for item in items:
            text = None

            if isinstance(item, str):
                text = item
            elif isinstance(item, dict) and prose_key:
                text = item.get(prose_key)

            if not isinstance(text, str):
                kept_items.append(item)
                continue

            claim = _matched_claim(
                text,
                claim_token_lists,
            )

            if claim:
                removed.append(
                    {
                        "field": field,
                        "text": text,
                        "claim": claim,
                    }
                )
                fields.add(field)
            else:
                kept_items.append(item)

        if field in fields:
            filtered[field] = kept_items

    # Insights ---------------------------------------------------------------
    # insights[] entries are {"type", "insight"} dicts (or plain strings).
    # They duplicate the typed narrative arrays, so the same unsupported
    # claim previously survived here even after being stripped from
    # bull_case/bear_case/catalysts.

    insights = filtered.get("insights")

    if isinstance(insights, list):
        kept_insights: list[Any] = []

        for item in insights:
            text = (
                item.get("insight")
                if isinstance(item, dict)
                else item
            )

            if isinstance(text, str):
                claim = _matched_claim(
                    text,
                    claim_token_lists,
                )

                if claim:
                    removed.append(
                        {
                            "field": "insights",
                            "text": text,
                            "claim": claim,
                        }
                    )
                    fields.add("insights")
                    continue

            kept_insights.append(item)

        if "insights" in fields:
            filtered["insights"] = kept_insights

    if not fields:
        return llm_output, None

    return filtered, {
        "fields": sorted(fields),
        "removed": removed[:20],
    }


def _rag_gap_diagnostic(
    news_count: Any,
    rag_context: Any,
) -> str | None:
    """
    Diagnostic when source news exists but RAG retrieval returns nothing.

    This identifies a retrieval-boundary problem such as:
      - missing embeddings
      - embedding ingestion failure
      - embedding dimension mismatch
      - company_id metadata mismatch
      - overly restrictive filters
    """

    try:
        rag_news = (rag_context or {}).get("news") or []
    except AttributeError:
        rag_news = []

    count = int(news_count or 0)

    if count > 0 and not rag_news:
        return (
            f"news_snapshot has {count} items but RAG 'news' retrieval "
            "returned zero documents. Possible causes: missing embeddings, "
            "embedding ingestion failure, company_id metadata mismatch, "
            "embedding dimension mismatch, or overly restrictive retrieval "
            "filters. Check embedding ingestion and retrieval metadata."
        )

    return None

def _filter_verified_claims(
    source_backed_claims: list[dict[str, Any]],
    claim_validation: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Return only claims explicitly verified by claim validation.
    """

    supported = {
        item.get("claim")
        for item in claim_validation
        if isinstance(item, dict)
        and item.get("status") == "supported"
    }

    return [
        claim
        for claim in source_backed_claims
        if isinstance(claim, dict)
        and claim.get("claim") in supported
    ]


# ---------------------------------------------------------------------------
# Numeric-assertion extraction
# ---------------------------------------------------------------------------
#
# The structured claim-validation loop (pipeline.py) only visits `causes` and
# `source_backed_claims`, treating each entry as one atomic claim. Free-text
# fields (insights, bear_case, market_interpretation) are never decomposed,
# so a compound sentence like "operating income fell to $398M from $941M in
# Q1 2026" validates only the primary fact while the embedded comparison
# figure floats unchecked. This module extracts standalone numeric assertions
# from the free-text fields, marks any that aren't already covered by a
# claim_validation entry as unsupported/unavailable, and hands them back so
# the existing sentence-level narrative filter can strip the hosting
# sentences — the same mechanism that already removes unsupported FCF/margin
# claims.
#
# The goal is NOT to validate the numbers against a source (that requires
# canonical-fact resolution which only the structured-source path does). The
# goal is purely to make the evidence gap VISIBLE: an unvalidated number in
# the narrative is either validated (appears in claim_validation) or flagged
# and stripped. It never silently survives.


# Matches a numeric fact in prose: optional comparison prefix ("from", "to",
# "of"), then a currency/percentage/count amount, optionally followed by a
# trailing period reference ("in Q1 2026", "for FY2027"). The prefix and
# trailing period are part of the match so the narrative filter can locate and
# remove the whole phrase.
_NUMERIC_ASSERTION_RE = re.compile(
    r"""
    (?:from|to|of|at|by|versus|vs\.?)\s+
    (?:
        # Currency: $941 million, $1.2B, $398M
        \$\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|trillion|[mbt]|mn|bn)?
        |
        # Bare amount: 941 million, 1.2 billion (no $)
        [\d,]+(?:\.\d+)?\s*(?:million|billion|trillion|[mbt]|mn|bn)
        |
        # Percentage: 27.2%, 30 percent
        [\d,]+(?:\.\d+)?\s*(?:percent|percentage(?:\s+points)?|bps?|basis\s+points?)
        |
        # Bare percent sign: 27.2%
        [\d,]+(?:\.\d+)?\s*%
    )
    # Optional trailing period reference.
    (?:\s+(?:in|for|during|over)\s+[A-Za-z]*\d{1,2}\s*(?:FY|Q)?\s*\d{4})?
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _extract_numeric_assertions(text: str) -> list[str]:
    """
    Extract standalone numeric assertions from a prose string.

    Returns the matched substrings (trimmed), deduplicated and ordered by
    first appearance.
    """
    if not isinstance(text, str):
        return []

    seen: set[str] = set()
    assertions: list[str] = []

    for match in _NUMERIC_ASSERTION_RE.finditer(text):
        assertion = match.group(0).strip()

        if not assertion:
            continue

        token = assertion.lower()

        if token in seen:
            continue

        seen.add(token)
        assertions.append(assertion)

    return assertions


def _claim_texts(claim_validation: list[dict[str, Any]]) -> set[str]:
    """Return the lowercase texts of all entries in claim_validation."""
    texts: set[str] = set()

    for item in claim_validation:
        if not isinstance(item, dict):
            continue

        claim = item.get("claim")

        if isinstance(claim, str):
            texts.add(claim.strip().lower())

    return texts


def _numeric_assertion_covered(
    assertion: str,
    claim_texts: set[str],
) -> bool:
    """
    Return True if a numeric assertion is already covered by an existing
    claim_validation entry.

    Coverage is asserted when any existing claim text contains the numeric
    core of the assertion (the amount, without the comparison prefix or
    trailing period). This prevents flagging a number that was already
    validated just because it appears in a different sentence context.
    """
    if not claim_texts:
        return False

    # Strip the comparison prefix and trailing period reference to isolate
    # the numeric core.
    core = assertion
    prefix_match = re.match(
        r"^(?:from|to|of|at|by|versus|vs\.?)\s+",
        core,
        re.IGNORECASE,
    )

    if prefix_match:
        core = core[prefix_match.end():]

    trailing_match = re.search(
        r"\s+(?:in|for|during|over)\s+[A-Za-z]*\d{1,2}\s*(?:FY|Q)?\s*\d{4}\s*$",
        core,
        re.IGNORECASE,
    )

    if trailing_match:
        core = core[: trailing_match.start()]

    core = core.strip().lower()

    if not core:
        return False

    for claim_text in claim_texts:
        if core in claim_text:
            return True

    return False


def _augment_claim_validation_with_numeric_assertions(
    llm_output: dict[str, Any],
    claim_validation: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Find numeric assertions in the free-text fields that aren't covered by
    any existing claim_validation entry, and append them as unsupported.

    Free-text fields are the ones the structured validation loop never
    visits. Each uncovered numeric assertion becomes an
    unsupported/unavailable claim_validation entry so the narrative filter
    can strip the sentence hosting it.
    """
    if not isinstance(claim_validation, list):
        claim_validation = []

    free_text_fields = (
        "summary",
        "market_interpretation",
        "bear_case",
        "risks",
        "insights",
        "invalidating_conditions",
    )

    has_free_text = any(
        isinstance(llm_output.get(field), (str, list))
        for field in free_text_fields
    )

    if not has_free_text:
        return claim_validation

    claim_texts = _claim_texts(claim_validation)

    candidates: list[str] = []
    seen: set[str] = set()

    for field in free_text_fields:
        value = llm_output.get(field)

        if isinstance(value, str):
            fragments = [value]
        elif isinstance(value, list):
            fragments = []
            for item in value:
                if isinstance(item, str):
                    fragments.append(item)
                elif isinstance(item, dict):
                    insight = item.get("insight")
                    if isinstance(insight, str):
                        fragments.append(insight)
        else:
            fragments = []

        for fragment in fragments:
            for assertion in _extract_numeric_assertions(fragment):
                token = assertion.lower()

                if token in seen:
                    continue

                seen.add(token)

                if _numeric_assertion_covered(assertion, claim_texts):
                    continue

                candidates.append(assertion)

    if not candidates:
        return claim_validation

    augmented = list(claim_validation)

    for assertion in candidates:
        augmented.append(
            {
                "claim": assertion,
                "status": "unsupported",
                "evidence_status": "unavailable",
                "evidence_ids": [],
                "validation_mode": "numeric_extraction",
                "source": "free_text",
            }
        )

    return augmented


def _derive_insights(
    llm_output: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Derive ``insights[]`` from the (already claim-filtered) narrative.

    insights[] is a typed projection of bull_case / bear_case / catalysts
    and the investment thesis — never an independent copy of the claims.
    Deriving from the filtered fields keeps a single source of truth so a
    claim removed by the narrative filter cannot survive verbatim in
    insights. Exact duplicates (same normalized text) are emitted once.
    """

    derived: list[dict[str, str]] = []
    seen: set[str] = set()

    for key in ("bull_case", "bear_case", "catalysts"):
        items = llm_output.get(key)

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, str) or not item.strip():
                continue

            token = " ".join(item.lower().split())

            if token in seen:
                continue

            seen.add(token)
            derived.append(
                {
                    "type": key,
                    "insight": item.strip(),
                }
            )

    thesis = llm_output.get("investment_thesis")

    if isinstance(thesis, str) and thesis.strip():
        token = " ".join(thesis.lower().split())

        if token not in seen:
            seen.add(token)
            derived.append(
                {
                    "type": "investment_thesis",
                    "insight": thesis.strip(),
                }
            )

    return derived


class CompanyAnalysisService:
    """Canonical persistence writer for the `analyses` contract."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _fill_analysis(
        self,
        analysis: Analysis,
        *,
        company: Company,
        context: dict[str, Any],
        llm_output: dict[str, Any],
        score: Any,
        evidence_package: dict[str, Any],
        duration_seconds: float,
    ) -> None:
        meta = llm_output.get("_meta", {})

        analysis.market_snapshot = jsonable_encoder(
            context.get("market_snapshot")
        )

        analysis.fundamental_snapshot = jsonable_encoder(
            context.get("fundamental_snapshot")
        )

        analysis.technical_snapshot = jsonable_encoder(
            context.get("technical_snapshot")
        )

        analysis.news_snapshot = jsonable_encoder(
            context.get("news_snapshot")
        )

        analysis.macro_snapshot = jsonable_encoder(
            context.get("macro_snapshot")
        )

        analysis.risk_snapshot = jsonable_encoder(
            context.get("risk_snapshot")
        )

        analysis.llm_analysis = jsonable_encoder(
            {
                **llm_output,
                "_input_context": context,
                "_evidence": evidence_package,
                "_meta_full": meta,
                # The exact deterministic score this analysis row was built
                # on. API consumers use it for the recommendation block so
                # later score recalculation can never mutate this analysis.
                "_score_snapshot": _score_as_snapshot(score),
            }
        )

        # Deterministic scoring remains authoritative.
        analysis.investment_score = score.overall_score
        analysis.risk_score = score.risk_score
        analysis.confidence_score = score.confidence

        # Provenance.
        analysis.analysis_version = ANALYSIS_VERSION
        analysis.prompt_version = meta.get("prompt_version")
        analysis.llm_model = meta.get("model")
        analysis.llm_tokens_used = meta.get("tokens_used")
        analysis.duration_seconds = duration_seconds

    async def persist_evidence(
        self,
        analysis: Analysis,
        llm_output: dict[str, Any],
    ) -> None:
        """
        Persist ONLY verified source-backed claims.

        The caller must already have filtered source_backed_claims using
        claim_validation.
        """

        for claim_data in llm_output.get(
            "source_backed_claims",
            [],
        ):
            source = claim_data.get("source") or {}

            self.session.add(
                AnalysisSource(
                    analysis_id=analysis.id,
                    claim=claim_data.get("claim", ""),
                    source_type=source.get("type", ""),
                    source_name=source.get("source", ""),
                    metric=source.get("metric"),
                    value=_safe_float(source.get("value")),
                    period=source.get("period"),
                )
            )

    async def persist_analysis(
        self,
        *,
        company: Company,
        context: dict[str, Any],
        llm_output: dict[str, Any],
        score: Any,
        evidence_package: dict[str, Any],
        duration_seconds: float,
        existing: Analysis | None = None,
    ) -> Analysis:
        """Write the full canonical contract."""

        if existing is not None:
            analysis = existing
        else:
            from uuid import uuid4

            analysis = Analysis(
                analysis_id=str(uuid4()),
                company_id=company.id,
                analysis_type="company",
            )

            self.session.add(analysis)

            # Required before AnalysisSource rows reference analysis.id.
            await self.session.flush()

        self._fill_analysis(
            analysis,
            company=company,
            context=context,
            llm_output=llm_output,
            score=score,
            evidence_package=evidence_package,
            duration_seconds=duration_seconds,
        )

        analysis.status = "completed"

        await self.persist_evidence(
            analysis,
            llm_output,
        )

        await self.session.commit()
        await self.session.refresh(analysis)

        return analysis


def assert_completed_analysis_contract(
    analysis: Any,
) -> None:
    """Assert the canonical completed-analysis invariant."""

    assert analysis.status == "completed"

    assert analysis.investment_score is not None
    assert analysis.risk_score is not None
    assert analysis.confidence_score is not None

    assert analysis.analysis_version == ANALYSIS_VERSION

    assert analysis.prompt_version
    assert analysis.llm_model
    assert analysis.llm_tokens_used is not None
    assert analysis.duration_seconds is not None

    for column in (
        "market_snapshot",
        "fundamental_snapshot",
        "technical_snapshot",
        "news_snapshot",
        "macro_snapshot",
        "risk_snapshot",
    ):
        value = getattr(analysis, column)

        assert isinstance(
            value,
            dict,
        ), f"{column} not a dict (got {type(value)})"

    blob = analysis.llm_analysis or {}

    assert blob.get("summary")

    for key in (
        "_input_context",
        "_evidence",
        "_meta_full",
    ):
        assert key in blob


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------

_framework_pipeline_factory = None


def _build_framework_pipeline():
    global _framework_pipeline_factory

    if _framework_pipeline_factory is None:
        from app.domains.stock.pipeline_factory import build_stock_pipeline

        _framework_pipeline_factory = build_stock_pipeline

    return _framework_pipeline_factory()


async def _load_latest_score(
    session: AsyncSession,
    company_id: int,
) -> Any:
    """Load the deterministic score written by the pipeline."""

    from app.domains.stock.models.analysis import InvestmentScore

    result = await session.execute(
        select(InvestmentScore)
        .where(
            InvestmentScore.company_id == company_id
        )
        .order_by(
            InvestmentScore.timestamp.desc()
        )
        .limit(1)
    )

    return result.scalars().first()


async def _execute_framework(
    session: AsyncSession,
    company: Company,
    *,
    existing: Analysis | None,
    on_stage: StageCallback | None,
    score_loader=None,
) -> AnalysisExecutionResult:
    """Run IntelligencePipeline and persist its canonical row."""

    from app.shared.entities import (
        AnalysisRequest,
        EntityRef,
    )

    async def stage(name: str) -> None:
        if on_stage is not None:
            await on_stage(name)

    await stage("calculating_metrics")

    started = time.monotonic()

    pipeline = _build_framework_pipeline()

    request = AnalysisRequest(
        entity_ref=EntityRef(
            "stock",
            "company",
            company.ticker,
        ),
        analysis_type="company",
    )

    result = await pipeline.run(request)

    if result.status != "completed":
        raise RuntimeError(
            f"framework analysis failed for {company.ticker}: "
            f"{result.metadata.get('stages', {})}"
        )

    score = await (
        score_loader or _load_latest_score
    )(
        session,
        company.id,
    )

    if score is None:
        raise RuntimeError(
            f"framework analysis produced no deterministic score "
            f"row for {company.ticker}"
        )

    meta_src = result.metadata or {}

    raw_llm_output = (
        meta_src.get("llm_output") or {}
    )

    # Preserve the complete claim audit trail.
    claim_validation_audit = (
        raw_llm_output.get("claim_validation", [])
    )

    # -----------------------------------------------------------------------
    # Populate insights from LLM structured output
    # -----------------------------------------------------------------------
    # insights[] is a typed projection of bull_case/bear_case/catalysts and
    # the investment thesis — never an independent copy of the claims. When
    # the LLM did not emit its own insights, they are REBUILT after claim
    # filtering (see below) from the already-filtered narrative, so a claim
    # stripped from bull_case cannot survive verbatim in insights.
    llm_insights = raw_llm_output.get("insights", [])
    insights_derived = not llm_insights

    # -----------------------------------------------------------------------
    # Populate recommendation_details from deterministic score
    # -----------------------------------------------------------------------
    # Preserve the raw LLM verdict (structured dict form) for the conflict
    # audit BEFORE sanitization removes it from the output payload.
    llm_verdict_raw = raw_llm_output.get(
        "recommendation"
    )

    raw_llm_output = _sanitize_llm_recommendation(
        raw_llm_output,
        score,
    )

    reco_details = raw_llm_output.get("recommendation_details", {})
    if not reco_details or not isinstance(reco_details, dict):
        reco_details = {}
    # Always include the deterministic recommendation info
    if score is not None:
        reco_details.update({
            "score": score.overall_score,
            "confidence": score.confidence,
            "recommendation": getattr(
                score, "recommendation", None
            ) or "HOLD",
            "reasons": reco_details.get("reasons", []),
            "score_source": "deterministic_scoring",
        })

    llm_output = {
        **raw_llm_output,

        "summary": result.summary,
        "insights": llm_insights,
        "risks": result.risks,
        "confidence": result.confidence,
        # NOTE: the LLM's own `recommendation` verdict is intentionally NOT
        # re-injected here. _sanitize_llm_recommendation() strips it because
        # the deterministic score is the only authoritative verdict; re-adding
        # it recreated the split-brain where `analysis.recommendation`
        # (LLM: "WATCH") contradicted `investment_score`/`recommendation.*`
        # (deterministic). Consumers read `recommendation_details` instead.

        # Initially obtain claims from the pipeline.
        "source_backed_claims": meta_src.get(
            "source_backed_claims",
            raw_llm_output.get(
                "source_backed_claims",
                [],
            ),
        ),

        # FULL audit trail remains untouched.
        "claim_validation": claim_validation_audit,

        "recommendation_details": reco_details,

        "evidence": (
            meta_src.get("llm_evidence")
            or {
                "evidence_sources": [
                    {
                        "source_type": e.source_type,
                        "source_name": e.source_name,
                        "metric": e.metric,
                        "value": e.value,
                        "period": e.period,
                    }
                    for e in result.evidence
                ],
                "source_count": len(result.evidence),
            }
        ),

        "rag_context": meta_src.get(
            "rag_context",
            {},
        ),

        "_meta": {
            **raw_llm_output.get("_meta", {}),
            "model": meta_src.get("llm_model"),
            "provider": meta_src.get("llm_provider"),
            "prompt_name": meta_src.get("prompt_name"),
            "prompt_version": meta_src.get("prompt_version"),
            "analysis_type": meta_src.get("analysis_type"),
            "tokens_used": meta_src.get("llm_tokens"),
        },
    }

    # -----------------------------------------------------------------------
    # Evidence gate
    # -----------------------------------------------------------------------

    claim_validation = claim_validation_audit

    # Surface numeric assertions embedded in free-text fields that the
    # structured validation loop never visits. Any number not already
    # covered by a claim_validation entry is appended as
    # unsupported/unavailable so the narrative filter can strip the hosting
    # sentence — closing the gap where a compound sentence's secondary fact
    # (e.g. a Q1 comparison figure) floated through unchecked.
    claim_validation = (
        _augment_claim_validation_with_numeric_assertions(
            llm_output,
            claim_validation,
        )
    )

    if claim_validation:
        # ONLY supported claims can become canonical source-backed claims.
        llm_output["source_backed_claims"] = (
            _filter_verified_claims(
                llm_output["source_backed_claims"],
                claim_validation,
            )
        )

        # Remove unsupported/conflicting factual assertions from narrative.
        llm_output, narrative_filter = (
            strip_unsupported_from_narrative(
                llm_output,
                claim_validation,
            )
        )

        # (insights are rebuilt from the filtered narrative below,
        #  outside the claim_validation guard, so the projection runs
        #  regardless of whether any claims were validated.)

        if narrative_filter is not None:
            validation_meta = (
                llm_output.get("_validation")
            )

            if not isinstance(validation_meta, dict):
                validation_meta = {}

            llm_output["_validation"] = {
                **validation_meta,
                "narrative_filtered": narrative_filter,
            }

    # Rebuild derived insights from the (possibly filtered) narrative so
    # insights[] has exactly one source of truth.  This lives outside the
    # claim_validation guard because the LLM usually does not emit insights
    # and the projection must be produced regardless of whether any claims
    # were validated.
    if insights_derived:
        llm_output["insights"] = _derive_insights(llm_output)

    # -----------------------------------------------------------------------
    # RAG diagnostic
    # -----------------------------------------------------------------------

    snapshots = (
        meta_src.get("domain_snapshots")
        or {}
    )

    news_snapshot = (
        snapshots.get("news_snapshot")
        or {}
    )

    rag_gap = _rag_gap_diagnostic(
        news_snapshot.get("news_count"),
        meta_src.get("rag_context"),
    )

    if rag_gap:
        stage_details = meta_src.setdefault(
            "stage_details",
            {},
        )

        rag_issues = stage_details.setdefault(
            "rag",
            [],
        )

        if (
            isinstance(rag_issues, list)
            and rag_gap not in rag_issues
        ):
            rag_issues.append(rag_gap)

        validation_meta = (
            llm_output.get("_validation")
        )

        if not isinstance(validation_meta, dict):
            validation_meta = {}

        diagnostics = list(
            validation_meta.get("diagnostics") or []
        )

        if rag_gap not in diagnostics:
            diagnostics.append(rag_gap)

        llm_output["_validation"] = {
            **validation_meta,
            "diagnostics": diagnostics,
        }

    # -----------------------------------------------------------------------
    # Deterministic recommendation is authoritative
    # -----------------------------------------------------------------------

    llm_reco = llm_verdict_raw

    if isinstance(llm_reco, dict):
        stated = (
            llm_reco.get("recommendation")
            or llm_reco.get("action")
        )

        deterministic = (
            score.recommendation
            if score is not None
            else None
        )

        if (
            stated
            and deterministic
            and _reco_bucket(stated)
            != _reco_bucket(deterministic)
        ):
            validation_meta = (
                llm_output.get("_validation")
            )

            if not isinstance(validation_meta, dict):
                validation_meta = {}

            issues = list(
                validation_meta.get("issues") or []
            )

            issues.append(
                "LLM recommendation conflicts with the "
                "deterministic score: "
                f"LLM='{stated}', "
                f"deterministic='{deterministic}'. "
                "The deterministic recommendation is authoritative."
            )

            llm_output["_validation"] = {
                **validation_meta,
                "status": "recommendation_conflict",
                "issues": issues,
            }

    # -----------------------------------------------------------------------
    # Persist
    # -----------------------------------------------------------------------

    risk_snapshot = snapshots.get(
        "risk_snapshot"
    )

    if not isinstance(risk_snapshot, dict):
        risk_snapshot = {}

    snapshots["risk_snapshot"] = {
        **risk_snapshot,
        "risk_score": score.risk_score,
        "score_source": "deterministic_scoring",
    }

    service = CompanyAnalysisService(session)

    analysis = await service.persist_analysis(
        company=company,
        context={
            "entity": {
                "id": company.ticker,
            },
            "rag_context": meta_src.get(
                "rag_context",
                {},
            ),
            "evidence": llm_output["evidence"],
            **snapshots,
        },
        llm_output=llm_output,
        score=score,
        evidence_package=llm_output["evidence"],
        duration_seconds=round(
            time.monotonic() - started,
            3,
        ),
        existing=existing,
    )

    return AnalysisExecutionResult(
        analysis=analysis,
        score=score,
        llm_output=llm_output,
        context={},
        evidence_package=llm_output["evidence"],
    )


async def execute_company_analysis(
    session: AsyncSession,
    company: Company,
    *,
    existing: Analysis | None = None,
    on_stage: StageCallback | None = None,
    score_loader=None,
) -> AnalysisExecutionResult:
    """
    THE production dispatch point for company analysis.

    Gate 6: framework is the only production analysis engine.
    """

    return await _execute_framework(
        session,
        company,
        existing=existing,
        on_stage=on_stage,
        score_loader=score_loader,
    )
