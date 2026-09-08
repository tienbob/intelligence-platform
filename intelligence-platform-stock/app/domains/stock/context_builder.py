"""
Stock domain context builder — builds structured context for LLM analysis.

Adapts the original ContextBuilder (scoring/context_builder.py) to the
domain-neutral IntelligenceContext format. Instead of accepting a SQLAlchemy
session, this builder extracts data from pipeline Observations collected by
the generic provider ``fetch()`` protocol (kinds: price_quote, news,
financials, balance_sheet, cash_flow, ratios, profile, macro, insider,
institutional).

Design invariants
-----------------
1. Canonical financial metrics are derived from one coherent reporting period.
2. revenue_growth_yoy is always measured against the comparable year-ago
   quarter, never the immediately preceding quarter.
3. Numeric zero is a valid value and must never be confused with "missing".
4. Company-scoped news/events require identity matching first. Textual
   relevance is only a fallback for untagged news.
5. Persisted snapshots must not resurrect stale values when a canonical
   observation explicitly says the value is unavailable.
6. Market one-day change ratio and percent are derived from the same fields.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any, Iterable

from app.core.logging import get_logger
from app.shared.entities import EntityRef, Evidence, IntelligenceContext, Observation

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _by_kind(
    observations: list[Observation],
    *kinds: str,
) -> list[Observation]:
    """Return observations whose kind is one of ``kinds``."""
    allowed = set(kinds)
    return [observation for observation in observations if observation.kind in allowed]


def _first_not_none(*values: Any) -> Any:
    """Return the first value that is not None.

    Unlike ``a or b``, this preserves legitimate zero/False values.
    """
    for value in values:
        if value is not None:
            return value
    return None


def _parse_date(value: Any) -> date | None:
    """Parse a provider date/datetime into a date."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    # Fast path for ISO dates/datetimes.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    # Common provider formats.
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue

    return None


def _normalize_published_at(value: Any) -> str | None:
    """Normalize a news timestamp to an ISO-8601 string.

    Accepts ISO strings, datetime objects, and Unix timestamps (int/float).
    Returns None for missing or unparseable values.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day).isoformat()

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            seconds = float(value)

            # Provider timestamps may be seconds or milliseconds
            # (e.g. finnhub); 1e12 as seconds would be year ~33000+ and
            # raise, silently dropping the timestamp.
            if seconds > 1e12:
                seconds /= 1000.0

            return datetime.fromtimestamp(
                seconds, tz=timezone.utc
            ).isoformat()
        except (ValueError, OSError, OverflowError):
            return None

    text = str(value).strip()
    if not text:
        return None

    # ISO string fast path.
    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).isoformat()
    except ValueError:
        pass

    # Common provider formats.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).isoformat()
        except ValueError:
            continue

    return None


def _period_key(row: dict[str, Any]) -> tuple[int | None, int | None, str | None, date | None]:
    """Extract a normalized year/quarter/form/date tuple from a provider row."""
    period_value = row.get("period") or row.get("fp")
    period_type = row.get("period_type")
    fiscal_year = row.get("fiscal_year", row.get("fy"))

    year: int | None = None
    quarter: int | None = None

    if fiscal_year is not None:
        try:
            year = int(fiscal_year)
        except (TypeError, ValueError):
            year = None

    period_text = str(period_value or "").upper()

    quarter_match = re.search(r"\bQ([1-4])\b", period_text)
    if quarter_match:
        quarter = int(quarter_match.group(1))

    # Some providers expose fp directly as Q1/Q2/Q3/Q4.
    if quarter is None and period_text in {"Q1", "Q2", "Q3", "Q4"}:
        quarter = int(period_text[1])

    period_date = _parse_date(period_value)

    if year is None and period_date is not None:
        year = period_date.year

    # Infer quarter from a calendar date if necessary.
    if quarter is None and period_date is not None:
        quarter = ((period_date.month - 1) // 3) + 1

    normalized_type = str(period_type).lower() if period_type is not None else None

    return year, quarter, normalized_type, period_date


def _same_reporting_period(
    row: dict[str, Any],
    target: dict[str, Any],
    *,
    require_date: bool = False,
) -> bool:
    """Determine whether two statement rows represent the same period.

    Date equality is preferred when both records carry dates. Fiscal
    year/quarter matching is used as the fallback.
    """
    row_year, row_quarter, row_type, row_date = _period_key(row)
    target_year, target_quarter, target_type, target_date = _period_key(target)

    if row_date is not None and target_date is not None:
        if row_date == target_date:
            return True
        if require_date:
            return False

    if (
        row_year is not None
        and target_year is not None
        and row_quarter is not None
        and target_quarter is not None
    ):
        if row_year == target_year and row_quarter == target_quarter:
            return True

    # For annual-only records, year + annual type is enough.
    if (
        row_year is not None
        and target_year is not None
        and row_year == target_year
        and row_type == target_type
        and row_type == "annual"
    ):
        return True

    return False


def _aligned_concept_values(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select concept facts from the latest coherent filing period."""
    groups: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}

    for row in rows:
        key = (
            row.get("fiscal_year", row.get("fy")),
            row.get("period", row.get("fp")),
            row.get("form"),
        )
        groups.setdefault(key, []).append(row)

    if not groups:
        return {}

    def _latest_filed(group: list[dict[str, Any]]) -> str:
        return max(str(row.get("filed", "")) for row in group)

    selected = max(groups.values(), key=_latest_filed)

    result = {
        row.get("concept"): row.get("value")
        for row in selected
        if row.get("concept") and row.get("value") is not None
    }

    if selected:
        result["period"] = _first_not_none(
            selected[0].get("period"),
            selected[0].get("fp"),
        )
        result["fiscal_year"] = _first_not_none(
            selected[0].get("fiscal_year"),
            selected[0].get("fy"),
        )

    return result


def _year_ago_row_for(
    rows: list[dict[str, Any]],
    latest: dict[str, Any],
) -> dict[str, Any] | None:
    """Find the same fiscal quarter approximately one year earlier.

    Date/period matching is preferred. A positional ``rows[4]`` fallback is
    allowed only when the input is demonstrably quarterly and gap-free.

    Never substitutes the immediately preceding quarter for YoY.
    """
    if not rows or not latest:
        return None

    latest_period_type = latest.get("period_type")
    if latest_period_type == "annual":
        return None

    latest_date = _parse_date(latest.get("period") or latest.get("fp"))
    latest_year, latest_quarter, _, _ = _period_key(latest)

    if latest_date is None and latest_year is None:
        return None

    target_year = latest_year - 1 if latest_year is not None else None
    target_quarter = latest_quarter

    candidates: list[dict[str, Any]] = []

    for row in rows[1:]:
        if not isinstance(row, dict):
            continue

        row_period_type = row.get("period_type")
        if row_period_type == "annual":
            continue

        row_year, row_quarter, _, row_date = _period_key(row)

        # Strongest match: same fiscal/calendar year + quarter.
        if (
            target_year is not None
            and target_quarter is not None
            and row_year == target_year
            and row_quarter == target_quarter
        ):
            candidates.append(row)
            continue

        # Date-window fallback when the fiscal-quarter metadata is missing.
        if latest_date is not None and row_date is not None:
            try:
                target_date = latest_date.replace(year=latest_date.year - 1)
            except ValueError:
                # Handles Feb 29-style dates.
                target_date = latest_date.replace(
                    year=latest_date.year - 1,
                    day=min(latest_date.day, 28),
                )

            if abs((row_date - target_date).days) <= 60:
                candidates.append(row)

    if candidates:
        # Prefer the closest date to the expected year-ago date.
        if latest_date is not None:
            try:
                target_date = latest_date.replace(year=latest_date.year - 1)
            except ValueError:
                target_date = latest_date.replace(
                    year=latest_date.year - 1,
                    day=min(latest_date.day, 28),
                )

            return min(
                candidates,
                key=lambda row: abs(
                    (
                        _parse_date(row.get("period") or row.get("fp"))
                        or target_date
                    )
                    - target_date
                ),
            )

        return candidates[0]

    # Strictly-quarterly, gap-free positional fallback.
    quarterly_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("period_type") in (None, "quarterly")
    ]

    if len(quarterly_rows) == len(rows) and len(rows) > 4:
        # Verify the expected 1-year step rather than blindly trusting index 4.
        expected = rows[4]
        latest_date = _parse_date(latest.get("period") or latest.get("fp"))
        expected_date = _parse_date(
            expected.get("period") or expected.get("fp")
        )

        if latest_date is not None and expected_date is not None:
            if 300 <= (latest_date - expected_date).days <= 430:
                return expected

    return None


def _select_period_row(
    rows: list[dict[str, Any]],
    target: dict[str, Any],
) -> dict[str, Any]:
    """Select a row from a statement series matching ``target`` period.

    If the target period cannot be matched and the candidate series has no
    period metadata, the first row is used as a last-resort observation.
    """
    if not rows:
        return {}

    for row in rows:
        if isinstance(row, dict) and _same_reporting_period(row, target):
            return row

    # If rows have no usable period metadata at all, preserve provider order.
    has_period_metadata = any(
        (row.get("period") or row.get("fp") or row.get("fiscal_year") or row.get("fy"))
        for row in rows
        if isinstance(row, dict)
    )

    return rows[0] if not has_period_metadata else {}


def _canonical_change_facts(
    q: dict[str, Any],
) -> tuple[Any, float | None, float | None]:
    """Return ``(price, one-day change ratio, one-day change %)``.

    Both representations derive from the SAME provider fields.

    A provider-supplied zero change is treated as unavailable only when there
    is no non-zero change information available. Zero is otherwise preserved
    as a legitimate numeric value.
    """
    price = _first_not_none(q.get("price"), q.get("close"))
    change = q.get("change")
    provider_percent = q.get("change_percent")

    change_float: float | None = None
    if change is not None:
        try:
            change_float = float(change)
        except (TypeError, ValueError):
            change_float = None

    change_ratio: float | None = None
    change_percent: float | None = None

    # Prefer an explicit provider percentage when it is present, numeric, and not
    # a stale zero placeholder that contradicts a non-zero raw change.
    if provider_percent is not None:
        try:
            provider_percent_float = float(provider_percent)
        except (TypeError, ValueError):
            provider_percent_float = None

        if provider_percent_float is not None:
            is_stale_zero = (
                provider_percent_float == 0.0
                and change_float is not None
                and change_float != 0.0
            )
            if not is_stale_zero:
                change_percent = provider_percent_float
                change_ratio = provider_percent_float / 100.0

    # Derive both values from price/change when provider percent is absent or stale.
    if change_ratio is None and price is not None and change is not None:
        try:
            price_float = float(price)
        except (TypeError, ValueError):
            price_float = None

        if price_float is not None and change_float is not None:
            base = price_float - change_float

            if base != 0:
                change_ratio = change_float / base
                change_percent = change_ratio * 100.0

    return price, change_ratio, change_percent


def _normalize_company_name(name: str) -> list[str]:
    """Return normalized searchable company aliases."""
    if not name:
        return []

    text = name.strip().lower()

    # Remove legal suffixes.
    text = re.sub(
        r"\b(incorporated|inc|corp|corporation|company|co|limited|ltd|plc)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"[^a-z0-9&\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return []

    tokens = text.split()

    aliases = {
        text,
        " ".join(tokens),
    }

    # Add useful multi-word forms while avoiding arbitrary one-word aliases
    # unless the company itself is actually one word.
    if len(tokens) >= 2:
        aliases.add(tokens[0])
        aliases.add(" ".join(tokens[:2]))

    if len(tokens) == 1:
        aliases.add(tokens[0])

    return sorted(alias.upper() for alias in aliases if alias)


def _text_mentions_alias(text: str, aliases: Iterable[str]) -> bool:
    """Case-insensitive whole-word / phrase matching."""
    if not text:
        return False

    normalized = re.sub(r"\s+", " ", str(text).upper()).strip()

    for alias in aliases:
        alias_normalized = re.sub(r"\s+", " ", alias.upper()).strip()
        if not alias_normalized:
            continue

        # Ticker/phrase-safe matching. Avoid raw substring matching.
        pattern = r"(?<![A-Z0-9])" + re.escape(alias_normalized) + r"(?![A-Z0-9])"

        if re.search(pattern, normalized):
            return True

    return False


# ---------------------------------------------------------------------------
# Stock context builder
# ---------------------------------------------------------------------------


class StockContextBuilder:
    """
    Builds structured intelligence context for stock analysis.

    Sections:
        - Market snapshot (price, volume, change)
        - Technical snapshot (momentum derived from quotes)
        - Fundamental snapshot (revenue, margins, growth from statements)
        - News snapshot (recent headlines)
        - Event snapshot (insider/institutional activity)
        - Macro snapshot (FRED indicators)
        - Risk snapshot (engine-owned; noted in context)
    """

    async def build(
        self,
        entity_ref: EntityRef,
        evidence: list[Evidence],
        observations: list[Observation],
        rag_context: dict[str, Any],
        **kwargs: Any,
    ) -> IntelligenceContext:
        """
        Build the full intelligence context for a stock entity.
        """
        ticker = str(entity_ref.entity_id).upper()

        persisted = await self._build_persisted_context(ticker)

        # Worker-fed fallback: use persisted context when request-time
        # observations are absent.
        if not observations and persisted is not None:
            return IntelligenceContext(
                entity={
                    "ticker": ticker,
                    "domain": entity_ref.domain,
                    "entity_type": entity_ref.entity_type,
                },
                evidence=evidence,
                observations=[],
                rag_context=rag_context,
                domain_snapshots={
                    key: persisted.get(key, {})
                    for key in (
                        "market_snapshot",
                        "technical_snapshot",
                        "fundamental_snapshot",
                        "news_snapshot",
                        "event_snapshot",
                        "macro_snapshot",
                        "risk_snapshot",
                    )
                },
                metadata={
                    "ticker": ticker,
                    "context_version": "2.1",
                },
            )

        company_observations = self._company_observations(
            observations,
            ticker,
            search_tokens=await self._company_search_tokens(ticker),
        )

        quotes = _by_kind(company_observations, "price_quote")
        news = _by_kind(company_observations, "news")
        financials = _by_kind(company_observations, "financials")
        balances = _by_kind(company_observations, "balance_sheet")
        cashflows = _by_kind(company_observations, "cash_flow")
        ratios = _by_kind(company_observations, "ratios")
        profiles = _by_kind(company_observations, "profile")
        insider = _by_kind(company_observations, "insider")
        institutional = _by_kind(company_observations, "institutional")

        # Macro is intentionally global rather than company-scoped.
        macro = _by_kind(observations, "macro")

        profile: dict[str, Any] = {}
        if profiles and isinstance(profiles[0].data, dict):
            profile = profiles[0].data

        observed_snapshots = {
            "market_snapshot": self._build_market_snapshot(quotes),
            "technical_snapshot": self._build_technical_snapshot(quotes),
            "fundamental_snapshot": self._build_fundamental_snapshot(
                financials,
                balances,
                cashflows,
                ratios,
            ),
            "news_snapshot": self._build_news_snapshot(news),
            "event_snapshot": self._build_event_snapshot(insider, institutional),
            "macro_snapshot": self._build_macro_snapshot(macro),
            "risk_snapshot": self._build_risk_snapshot(),
        }

        if persisted is not None:
            persisted_snapshots = {
                key: persisted.get(key, {})
                for key in observed_snapshots
            }

            snapshots: dict[str, dict[str, Any]] = {}

            # Fields that are derived from the current observation stream.
            # If a new observation explicitly says these are unavailable,
            # stale persisted values must NOT survive the merge.
            replace_missing_fields: dict[str, set[str]] = {
                "market_snapshot": {
                    "price_change_1d",
                    "price_change_1d_pct",
                    "latest_volume",
                    "latest_date",
                    "latest_price",
                },
                "technical_snapshot": {
                    "momentum_1d_pct",
                },
                "fundamental_snapshot": {
                    "revenue_growth_yoy",
                },
            }

            for key, observed in observed_snapshots.items():
                stored = persisted_snapshots[key]
                stored = stored if isinstance(stored, dict) else {}
                observed = observed if isinstance(observed, dict) else {}

                merged = dict(stored)

                # Explicitly clear fields whose current observation says
                # unavailable, rather than resurrecting stale persisted data.
                for field in replace_missing_fields.get(key, set()):
                    if field in observed and observed[field] is None:
                        merged.pop(field, None)

                for name, value in observed.items():
                    if value is None:
                        continue

                    # Provider zero volume is invalid/unavailable unless it is
                    # explicitly handled upstream. Never overwrite a valid
                    # persisted volume with provider 0.
                    if name == "latest_volume" and value == 0:
                        continue

                    merged[name] = value

                snapshots[key] = merged
        else:
            snapshots = observed_snapshots

        context = IntelligenceContext(
            entity={
                "id": ticker,
                "ticker": ticker,
                "name": profile.get("name")
                or profile.get("companyName")
                or ticker,
                "sector": profile.get("sector"),
                "industry": profile.get("industry"),
                "market_cap": profile.get("marketCap"),
                "domain": entity_ref.domain,
                "entity_type": entity_ref.entity_type,
            },
            evidence=evidence,
            observations=company_observations,
            rag_context=rag_context,
            domain_snapshots=snapshots,
            metadata={
                "ticker": ticker,
                "context_version": "2.1",
            },
        )

        logger.info(
            "Built full context for %s (obs=%d, company_obs=%d, evidence=%d, rag=%s)",
            ticker,
            len(observations),
            len(company_observations),
            len(evidence),
            bool(rag_context),
        )

        return context

    # -----------------------------------------------------------------------
    # Persisted context
    # -----------------------------------------------------------------------

    @staticmethod
    async def _build_persisted_context(
        ticker: str,
    ) -> dict[str, Any] | None:
        """Load worker-owned observations for request-time framework runs."""
        try:
            from app.core.database import async_session_factory
            from app.domains.stock.models.company import Company
            from app.domains.stock.scoring.context_builder import ContextBuilder
            from sqlalchemy import select

            async with async_session_factory() as session:
                result = await session.execute(
                    select(Company)
                    .where(Company.ticker == ticker.upper())
                    .limit(1)
                )
                company = result.scalar_one_or_none()

                if company is None:
                    return None

                return await ContextBuilder(session).build_full_context(company)

        except Exception as exc:
            logger.warning(
                "Persisted context unavailable for %s: %s",
                ticker,
                exc,
            )
            return None

    # -----------------------------------------------------------------------
    # Company identity / filtering
    # -----------------------------------------------------------------------

    @staticmethod
    async def _company_search_tokens(
        ticker: str,
    ) -> set[str]:
        """
        Return normalized ticker/company aliases for textual fallback matching.

        Identity matching remains preferred. Text matching is only used for
        untagged news.
        """
        tokens: set[str] = {ticker.upper()}

        try:
            from app.core.database import async_session_factory
            from app.domains.stock.models.company import Company
            from sqlalchemy import select

            async with async_session_factory() as session:
                name = (
                    await session.execute(
                        select(Company.name)
                        .where(Company.ticker == ticker.upper())
                        .limit(1)
                    )
                ).scalar_one_or_none()

            if name:
                tokens.update(_normalize_company_name(str(name)))

        except Exception as exc:
            logger.debug(
                "Unable to resolve company aliases for %s: %s",
                ticker,
                exc,
            )

        return tokens

    @classmethod
    def _company_observations(
        cls,
        observations: list[Observation],
        ticker: str,
        search_tokens: set[str] | None = None,
    ) -> list[Observation]:
        """
        Exclude unrelated provider observations from company analysis.

        Identity priority:
            1. Observation entity identity
            2. Explicit company_id
            3. Explicit ticker(s)
            4. Controlled textual fallback for untagged news only

        A bare global/latest-news feed is never accepted wholesale.
        """
        ticker_upper = ticker.upper()
        tokens = (
            {ticker_upper}
            if not search_tokens
            else {str(token).upper() for token in search_tokens}
        )

        relevant: list[Observation] = []

        for observation in observations:
            # Company/entity identity carried by the observation itself.
            obs_entity_ref = getattr(observation, "entity_ref", None)
            obs_entity_id = getattr(obs_entity_ref, "entity_id", None)

            if (
                obs_entity_id is not None
                and str(obs_entity_id).upper() != ticker_upper
                and observation.kind not in {"macro"}
            ):
                continue

            # Company/global observation types other than news/events are
            # expected to be company-scoped upstream.
            if observation.kind not in {"news", "event"}:
                # If the payload explicitly declares a company_id/ticker and
                # it contradicts the requested company, reject it.
                if isinstance(observation.data, dict):
                    company_id = observation.data.get("company_id")
                    item_ticker = observation.data.get("ticker")

                    if company_id is not None and str(company_id) != str(
                        getattr(obs_entity_ref, "entity_id", ticker)
                    ):
                        continue

                    if (
                        item_ticker is not None
                        and str(item_ticker).upper() != ticker_upper
                    ):
                        continue

                relevant.append(observation)
                continue

            # ---------------------------------------------------------------
            # News observations
            # ---------------------------------------------------------------
            if observation.kind == "news" and isinstance(observation.data, list):
                company_items: list[dict[str, Any]] = []

                for item in observation.data:
                    if not isinstance(item, dict):
                        continue

                    # Explicit company ID is strongest.
                    item_company_id = item.get("company_id")
                    if item_company_id is not None:
                        if str(item_company_id) == str(
                            getattr(obs_entity_ref, "entity_id", ticker)
                        ) or str(item_company_id) == ticker_upper:
                            company_items.append(item)
                        continue

                    # Verified ticker metadata.
                    item_tickers = {
                        str(value).upper()
                        for value in (item.get("tickers") or [])
                        if value is not None
                    }

                    item_ticker = item.get("ticker")
                    if item_ticker is not None:
                        item_tickers.add(str(item_ticker).upper())

                    if item_tickers:
                        if ticker_upper in item_tickers:
                            company_items.append(item)

                        # A tagged article for another ticker is rejected;
                        # never fall back to text matching for it.
                        continue

                    # Explicitly untagged item: controlled textual relevance
                    # fallback only.
                    haystack = " ".join(
                        str(item.get(key) or "")
                        for key in ("title", "summary", "content")
                    )

                    if _text_mentions_alias(haystack, tokens):
                        company_items.append(item)

                if company_items:
                    relevant.append(
                        replace(
                            observation,
                            data=company_items,
                        )
                    )

                continue

            # ---------------------------------------------------------------
            # Event observations
            # ---------------------------------------------------------------
            if not isinstance(observation.data, dict):
                relevant.append(observation)
                continue

            event_data = observation.data

            event_company_id = event_data.get("company_id")
            if event_company_id is not None:
                if str(event_company_id) != str(
                    getattr(obs_entity_ref, "entity_id", ticker)
                ) and str(event_company_id) != ticker_upper:
                    continue

            event_tickers = event_data.get("tickers") or []
            if event_tickers:
                if ticker_upper not in {
                    str(value).upper() for value in event_tickers
                }:
                    continue

            event_ticker = event_data.get("ticker")
            if (
                event_ticker is not None
                and str(event_ticker).upper() != ticker_upper
            ):
                continue

            relevant.append(observation)

        return relevant

    # -----------------------------------------------------------------------
    # Snapshot builders
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_market_snapshot(
        quote_obs: list[Observation],
    ) -> dict[str, Any]:
        """Market snapshot from the latest provider quote."""
        if not quote_obs:
            return {}

        q = (
            quote_obs[0].data
            if isinstance(quote_obs[0].data, dict)
            else {}
        )

        price, change_ratio, change_percent = _canonical_change_facts(q)

        return {
            "latest_price": price,
            "latest_volume": q.get("volume"),
            "price_change_1d": change_ratio,
            "price_change_1d_pct": change_percent,
            "latest_date": q.get("timestamp"),
            "source": quote_obs[0].source,
        }

    @staticmethod
    def _build_technical_snapshot(
        quote_obs: list[Observation],
    ) -> dict[str, Any]:
        """
        Technical snapshot from the canonical one-day market change.

        Detailed SMA/RSI/MACD indicators remain owned by the scoring engine.
        """
        q = (
            quote_obs[0].data
            if quote_obs and isinstance(quote_obs[0].data, dict)
            else {}
        )

        _, _, change_percent = _canonical_change_facts(q)

        return {
            "momentum_1d_pct": change_percent,
            "note": (
                "Detailed technical indicators (SMA/RSI/MACD) are computed "
                "by the domain scoring engine and reflected in the score."
            ),
        }

    @staticmethod
    def _build_fundamental_snapshot(
        financials: list[Observation],
        balances: list[Observation],
        cashflows: list[Observation],
        ratios: list[Observation],
    ) -> dict[str, Any]:
        """
        Build a coherent fundamental snapshot.

        Income statement period is selected first. Balance sheet, cash flow,
        and ratio rows are then aligned to that target period where provider
        period metadata permits.
        """
        snap: dict[str, Any] = {}

        latest_income: dict[str, Any] = {}
        year_ago_income: dict[str, Any] | None = None

        # ---------------------------------------------------------------
        # Income statement
        # ---------------------------------------------------------------
        if financials and isinstance(financials[0].data, list):
            rows = [
                row for row in financials[0].data
                if isinstance(row, dict)
            ]

            if rows and "revenue" in rows[0]:
                latest_income = rows[0]
                year_ago_income = _year_ago_row_for(
                    rows,
                    latest_income,
                )
            elif rows:
                latest_income = _aligned_concept_values(rows)

        if latest_income:
            revenue = latest_income.get("revenue")
            net_income = latest_income.get("net_income")
            gross_profit = latest_income.get("gross_profit")

            gross_margin = None
            if revenue is not None and gross_profit is not None:
                try:
                    if float(revenue) != 0:
                        gross_margin = round(
                            float(gross_profit) / float(revenue),
                            4,
                        )
                except (TypeError, ValueError):
                    gross_margin = None

            net_margin = None
            if revenue is not None and net_income is not None:
                try:
                    if float(revenue) != 0:
                        net_margin = round(
                            float(net_income) / float(revenue),
                            4,
                        )
                except (TypeError, ValueError):
                    net_margin = None

            snap.update(
                {
                    "revenue": revenue,
                    "net_income": net_income,
                    "gross_profit": gross_profit,
                    "gross_margin": gross_margin,
                    "net_margin": net_margin,
                    "operating_income": latest_income.get("operating_income"),
                }
            )

            # YoY only. Never silently substitute QoQ.
            if (
                year_ago_income is not None
                and year_ago_income.get("revenue") is not None
                and revenue is not None
            ):
                try:
                    prior_revenue = float(year_ago_income["revenue"])
                    current_revenue = float(revenue)

                    if prior_revenue != 0:
                        snap["revenue_growth_yoy"] = round(
                            (current_revenue - prior_revenue)
                            / prior_revenue,
                            4,
                        )
                except (TypeError, ValueError):
                    pass

        # ---------------------------------------------------------------
        # Determine canonical target period.
        # ---------------------------------------------------------------
        target_period = latest_income

        # ---------------------------------------------------------------
        # Balance sheet
        # ---------------------------------------------------------------
        balance_section: dict[str, Any] = {
            "source": balances[0].source if balances else None,
            "period": None,
            "mode": "unavailable",
        }

        if balances and isinstance(balances[0].data, list):
            rows = [
                row for row in balances[0].data
                if isinstance(row, dict)
            ]

            if rows and "total_assets" in rows[0]:
                b = _select_period_row(rows, target_period) if target_period else rows[0]

                if b:
                    balance_section["period"] = (
                        b.get("period")
                        or b.get("fp")
                        or b.get("fiscal_year")
                    )
                    balance_section["mode"] = "period_row"
                    snap.update(
                        {
                            "total_assets": b.get("total_assets"),
                            "total_debt": b.get("total_debt"),
                            "shareholders_equity": b.get("shareholders_equity"),
                            "cash": b.get("cash"),
                        }
                    )
                else:
                    # A target period existed but no balance-sheet row
                    # matched it. Values are deliberately NOT merged from a
                    # different period; the provenance block records why.
                    balance_section["mode"] = "no_period_match"

            elif rows:
                aligned = _aligned_concept_values(rows)
                balance_section["mode"] = "concept_alignment"
                snap.update(aligned)

        # ---------------------------------------------------------------
        # Cash flow
        # ---------------------------------------------------------------
        cashflow_section: dict[str, Any] = {
            "source": cashflows[0].source if cashflows else None,
            "period": None,
            "mode": "unavailable",
        }

        if cashflows and isinstance(cashflows[0].data, list):
            rows = [
                row for row in cashflows[0].data
                if isinstance(row, dict)
            ]

            if rows:
                has_period_metadata = any(
                    row.get("period") or row.get("fp")
                    for row in rows
                )

                c = None
                if target_period:
                    c = _select_period_row(rows, target_period)
                    if c:
                        cashflow_section["mode"] = "period_row"

                # If provider periods exist but no matching row was found,
                # do NOT silently combine a different period.
                if not c and not has_period_metadata:
                    c = rows[0]
                    cashflow_section["mode"] = "first_row_fallback"
                elif not c and not target_period:
                    c = rows[0]
                    cashflow_section["mode"] = "no_target_period"

                if c:
                    cashflow_section["period"] = (
                        c.get("period")
                        or c.get("fp")
                        or c.get("fiscal_year")
                    )
                    snap.update(
                        {
                            "operating_cash_flow": c.get("operating_cash_flow"),
                            "free_cash_flow": c.get("free_cash_flow"),
                            "capital_expenditure": c.get("capital_expenditure"),
                        }
                    )
                elif has_period_metadata:
                    # A target period existed but no cash-flow row matched
                    # it. Values are deliberately NOT merged from a
                    # different period; provenance records why.
                    cashflow_section["mode"] = "no_period_match"

        # ---------------------------------------------------------------
        # Ratios
        # ---------------------------------------------------------------
        ratios_section: dict[str, Any] = {
            "source": ratios[0].source if ratios else None,
            "period": None,
            "mode": "unavailable",
        }

        if ratios and isinstance(ratios[0].data, list):
            rows = [
                row for row in ratios[0].data
                if isinstance(row, dict)
            ]

            if rows:
                has_period_metadata = any(
                    row.get("period") or row.get("fp")
                    for row in rows
                )

                r0 = (
                    _select_period_row(rows, target_period)
                    if target_period
                    else None
                )

                if r0:
                    ratios_section["mode"] = "period_row"
                elif not has_period_metadata:
                    r0 = rows[0]
                    ratios_section["mode"] = "first_row_fallback"
                elif not target_period:
                    r0 = rows[0]
                    ratios_section["mode"] = "no_target_period"

                if r0:
                    ratios_section["period"] = (
                        r0.get("period")
                        or r0.get("fp")
                        or r0.get("fiscal_year")
                    )
                    snap.update(
                        {
                            "pe_ratio": r0.get("priceEarningsRatio"),
                            "roe": r0.get("returnOnEquity"),
                            "debt_to_equity": r0.get("debtEquityRatio"),
                            "ps_ratio": r0.get("priceToSalesRatio"),
                            "pb_ratio": r0.get("priceToBookRatio"),
                        }
                    )
                elif has_period_metadata:
                    ratios_section["mode"] = "no_period_match"

        snap["metrics"] = {
            key: snap[key]
            for key in (
                "revenue",
                "pe_ratio",
                "ps_ratio",
                "pb_ratio",
                "roe",
                "gross_margin",
                "net_margin",
                "debt_to_equity",
            )
            if key in snap and snap[key] is not None
        }

        # ---------------------------------------------------------------
        # Provenance
        # ---------------------------------------------------------------
        latest_period = (
            latest_income.get("period")
            or latest_income.get("fp")
            if latest_income
            else None
        )

        latest_fiscal_year = (
            latest_income.get("fiscal_year")
            or latest_income.get("fy")
            if latest_income
            else None
        )

        snap["latest_statement"] = {
            "period": latest_period,
            "fiscal_year": latest_fiscal_year,
            "source": financials[0].source if financials else None,
            "period_type": latest_income.get("period_type")
            if latest_income
            else None,
        }

        # Per-section provenance: which provider supplied each statement
        # section, which period row was actually selected, and whether
        # alignment succeeded. Financial fields for the SAME quarter were
        # observed to drift between runs (e.g. total_debt) or disappear
        # (cash-flow fields, revenue_growth_yoy) when a provider returned
        # different period coverage; this makes such divergence
        # attributable instead of silent.
        snap["provenance"] = {
            "income_statement": {
                "source": financials[0].source if financials else None,
                "period": latest_period,
                "fiscal_year": latest_fiscal_year,
                "period_type": (
                    latest_income.get("period_type")
                    if latest_income
                    else None
                ),
                "year_ago_row_found": year_ago_income is not None,
            },
            "balance_sheet": balance_section,
            "cash_flow": cashflow_section,
            "ratios": ratios_section,
        }

        return snap

    @staticmethod
    def _build_news_snapshot(
        news_obs: list[Observation],
    ) -> dict[str, Any]:
        """News snapshot from already company-scoped observations."""
        articles: list[dict[str, Any]] = []

        for obs in news_obs:
            items = (
                obs.data
                if isinstance(obs.data, list)
                else [obs.data]
            )

            for article in items:
                if not isinstance(article, dict):
                    continue

                if not article.get("title"):
                    continue

                articles.append(
                    {
                        "title": article.get("title", ""),
                        "summary": (article.get("summary") or "")[:280],
                        "source": obs.source,
                        "published_at": _normalize_published_at(
                            article.get("published_at")
                        ),
                        "url": article.get("url"),
                        "sentiment": article.get("sentiment"),
                    }
                )

        return {
            "recent_news": articles[:10],
            "news_count": len(articles),
        }

    @staticmethod
    def _build_event_snapshot(
        insider: list[Observation],
        institutional: list[Observation],
    ) -> dict[str, Any]:
        """Event snapshot from company-scoped insider/institutional activity."""
        events: list[dict[str, Any]] = []

        for obs in insider:
            items = obs.data if isinstance(obs.data, list) else []

            for transaction in items[:5]:
                if not isinstance(transaction, dict):
                    continue

                events.append(
                    {
                        "type": "insider_transaction",
                        "insider": transaction.get("insider_name"),
                        "transaction_type": transaction.get("transaction_type"),
                        "shares": transaction.get("shares"),
                        "date": transaction.get("transaction_date"),
                    }
                )

        for obs in institutional:
            items = obs.data if isinstance(obs.data, list) else []

            for ownership in items[:5]:
                if not isinstance(ownership, dict):
                    continue

                events.append(
                    {
                        "type": "institutional_ownership_change",
                        "institution": ownership.get("institution"),
                        "percent_change": ownership.get("percent_change"),
                        "date": ownership.get("filing_date"),
                    }
                )

        return {
            "recent_events": events,
            "event_count": len(events),
        }

    @staticmethod
    def _build_macro_snapshot(
        macro_obs: list[Observation],
    ) -> dict[str, Any]:
        """Macro snapshot from FRED indicator observations."""
        data: dict[str, Any] = {}

        for obs in macro_obs:
            items = (
                obs.data
                if isinstance(obs.data, list)
                else [obs.data]
            )

            for item in items:
                if not isinstance(item, dict):
                    continue

                metric = item.get("indicator") or item.get("series")
                value = item.get("value")

                if metric and value is not None:
                    data[str(metric)] = value

        return {
            "indicators": data,
            "note": "Macro indicators sourced from provider observations",
        }

    @staticmethod
    def _build_risk_snapshot() -> dict[str, Any]:
        """Risk snapshot — engine-owned; populated later by scoring."""
        return {
            "note": (
                "Risk metrics are owned by the deterministic scoring engine "
                "and are surfaced here when available."
            )
        }