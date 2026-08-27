"""
Entity Resolution Service — CANONICAL framework implementation.

This is the platform-wide source of truth for entity disambiguation and
identifier normalization. Domains do NOT reimplement these mechanics;
they *register* their domain-specific semantics here.

Architecture
------------
The framework owns the mechanics:
    - canonical EntityRef identity
    - identifier normalization dispatch
    - resolution lifecycle
    - cross-entity linking

The domain owns the semantics:
    - what an ID looks like ("AAPL", "cand-123", "property-42")
    - how ambiguous references are disambiguated against its own data

Domains register normalizers::

    # app/domains/stock/normalization/companies.py
    from app.intelligence.entity_resolution import register_normalizer

    register_normalizer("stock", "company", lambda eid: normalize_ticker(eid))

Unregistered domain/type pairs fall back to the framework default
(strip whitespace; uppercase short alphabetic symbols), which preserves
the original generic behavior.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from app.core.logging import get_logger
from app.shared.entities import EntityRef

logger = get_logger(__name__)

# A normalizer maps a raw entity_id string to its canonical form.
NormalizerFn = Callable[[str], str]


class EntityResolutionService:
    """
    Domain-agnostic entity resolution framework (canonical implementation).

    Resolves ambiguous entity references to canonical entities using
    registered domain normalizers. Domains register semantics; the
    framework owns the resolution pipeline.
    """

    def __init__(self) -> None:
        # (domain, entity_type) → normalizer chain ; "*" is a wildcard
        self._normalizers: dict[tuple[str, str], list[NormalizerFn]] = defaultdict(list)

    # ── Registration (domain-facing) ────────────────────────────

    def register_normalizer(
        self,
        domain: str,
        normalizer: NormalizerFn,
        entity_type: str = "*",
    ) -> None:
        """
        Register an identifier normalizer for a domain (optionally scoped
        to one entity type). Later registrations wrap earlier ones — the
        last-registered normalizer runs first (chaining support).
        """
        self._normalizers[(domain, entity_type)].append(normalizer)
        logger.debug(
            "Registered normalizer for %s/%s (total: %d)",
            domain,
            entity_type,
            len(self._normalizers[(domain, entity_type)]),
        )

    # ── Resolution ──────────────────────────────────────────────

    async def resolve(
        self,
        entity_ref: EntityRef,
        context: dict[str, Any] | None = None,
    ) -> EntityRef:
        """
        Resolve an entity reference to its canonical form.

        Uses the normalizer chain registered for its (domain, entity_type),
        falling back to framework-default normalization for unregistered
        domain/type pairs.
        """
        logger.debug(
            "Resolving entity: domain=%s type=%s id=%s",
            entity_ref.domain,
            entity_ref.entity_type,
            entity_ref.entity_id,
        )

        normalized_id = self.normalize_id(entity_ref)

        if normalized_id != entity_ref.entity_id:
            logger.debug(
                "Normalized entity ID: '%s' → '%s'",
                entity_ref.entity_id,
                normalized_id,
            )

        return EntityRef(
            domain=entity_ref.domain,
            entity_type=entity_ref.entity_type,
            entity_id=normalized_id,
        )

    def normalize_id(self, entity_ref: EntityRef) -> str:
        """
        Normalize an entity ID using the normalizer chain registered for
        its (domain, entity_type), falling back to framework defaults.
        Pure function of (domain, type, id).
        """
        chain: list[NormalizerFn] = []
        for key in (
            (entity_ref.domain, entity_ref.entity_type),
            (entity_ref.domain, "*"),
        ):
            chain.extend(reversed(self._normalizers.get(key, [])))

        if chain:
            # Domain-specific semantics own normalization entirely;
            # strip is applied as a universal baseline first.
            normalized = entity_ref.entity_id.strip()
            for normalizer in chain:
                normalized = normalizer(normalized)
            return normalized

        return self._default_normalize(entity_ref.entity_id)

    @staticmethod
    def _default_normalize(entity_id: str) -> str:
        """Framework-default normalization (preserves original behavior)."""
        normalized = entity_id.strip()
        # Uppercase ticker-like symbols (1-5 uppercase letters)
        if normalized.isalpha() and normalized.isascii() and len(normalized) <= 5:
            normalized = normalized.upper()
        return normalized

    async def link(
        self,
        source: EntityRef,
        targets: list[EntityRef],
    ) -> dict[str, list[EntityRef]]:
        """
        Link a source entity to related target entities.

        Args:
            source: The source entity to link from.
            targets: Candidate target entities.

        Returns:
            A dict mapping relationship types to lists of linked entities.
        """
        links: dict[str, list[EntityRef]] = {}

        for target in targets:
            relationship = self._infer_relationship(source, target)
            if relationship not in links:
                links[relationship] = []
            links[relationship].append(target)

        logger.debug(
            "Linked %d target(s) to %s/%s: %s",
            len(targets),
            source.entity_type,
            source.entity_id,
            {k: len(v) for k, v in links.items()},
        )
        return links

    def _normalize_id(self, entity_id: str) -> str:
        """Normalize an entity ID (strip whitespace, uppercase tickers, etc.)."""
        normalized = entity_id.strip()
        # Uppercase ticker-like symbols (1-5 uppercase letters)
        if normalized.isalpha() and normalized.isascii() and len(normalized) <= 5:
            normalized = normalized.upper()
        return normalized

    def _infer_relationship(
        self, source: EntityRef, target: EntityRef
    ) -> str:
        """
        Infer the relationship type between two entities.

        Override for domain-specific relationship inference.
        """
        if source.domain != target.domain:
            return "cross_domain"
        if source.entity_type == target.entity_type:
            return "same_type"
        return "related"


# ── Global singleton + registration helpers ─────────────────────

_service: EntityResolutionService | None = None


def get_entity_resolution_service() -> EntityResolutionService:
    """Get the global entity resolution service singleton."""
    global _service
    if _service is None:
        _service = EntityResolutionService()
    return _service


def register_normalizer(
    domain: str,
    normalizer: NormalizerFn,
    entity_type: str = "*",
) -> None:
    """Module-level convenience for registering a normalizer on the singleton."""
    get_entity_resolution_service().register_normalizer(domain, normalizer, entity_type)


def reset_entity_resolution_service() -> None:
    """Reset the singleton (useful for testing)."""
    global _service
    _service = None