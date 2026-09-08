"""
Evidence attribution — claim ↔ source relationships.

Every AI-generated claim must be traceable to its source evidence. This
module builds, validates, and enriches that attribution generically.

The framework owns generic provenance mechanics; domain-specific
attributors/resolvers own semantic validation such as metric, value,
period, fiscal year, and other domain-specific facts.

Important boundary:

    EvidenceAttributor
        - registers retrieved evidence
        - validates source identity
        - resolves cited evidence IDs
        - reports provenance failures

    Domain resolver
        - validates whether the evidence actually supports the claim
        - validates metric/value/period/etc.

A source merely existing in the registry is NOT sufficient to mark a
claim as factually supported.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

from app.intelligence.evidence.types import RagContext, source_id_for


class EvidenceAttributor:
    """
    Builds and validates evidence attribution for LLM claims.

    Domain-neutral: this class does not know what a revenue claim,
    financial period, HR fact, or other domain-specific fact means.

    It only establishes whether a cited evidence ID resolves to a
    structurally valid, identity-consistent registered source.

    Existing callers retain the legacy dict-based method shapes.
    """

    # Generic statuses understood by the evidence pipeline.
    SUPPORTED_STATUSES = {"supported", "resolved", "valid"}
    INVALID_STATUSES = {"invalid", "rejected", "error"}

    # Mapping from claim source type to compatible evidence entity_types.
    # Domains can extend this for domain-specific type compatibility.
    # A claim citing a "financial_statement" should be backed by "filing"
    # evidence, not "news".
    CLAIM_SOURCE_TYPE_COMPATIBILITY: dict[str, set[str]] = {
        "financial_statement": {"filing", "financial_statement"},
        "financial": {"filing", "financial_statement", "financial_data"},
        "sec_filing": {"filing", "sec_filing"},
        "news_article": {"news"},
        "news": {"news"},
        "analysis_report": {"analysis"},
        "market_data": {"price", "technical"},
    }

    # Evidence types that are themselves generated AI output (e.g. previous
    # analyses). They are legitimate registered provenance, but they cannot
    # FACTUALLY ground a claim: an earlier model asserting a number does not
    # make the number true. Without this guard, the same fact validated as
    # "supported" (claim without a typed source block, so no type-compat
    # check ran) or "unsupported" (typed source block rejected the analysis
    # evidence) depending purely on how the LLM phrased the claim.
    DERIVED_EVIDENCE_TYPES: frozenset[str] = frozenset({"analysis"})

    def __init__(self) -> None:
        self.source_registry: dict[str, dict[str, Any]] = {}
        self.invalid_sources: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_sources(
        self,
        rag_context: RagContext,
    ) -> list[dict[str, Any]]:
        """
        Register RAG sources and build the evidence registry.

        Args:
            rag_context:
                entity_type -> list of retrieval result dicts.

        Returns:
            List of valid registered evidence-source dicts.

        A source is rejected when its identity is malformed or internally
        inconsistent. Rejected sources are preserved in ``invalid_sources``
        for diagnostics.

        Canonical source IDs have the form:

            <entity_type>_<entity_id>

        Example:

            news_782
            sec_filing_123
            event_42
        """
        self.source_registry = {}
        self.invalid_sources = []

        evidence_sources: list[dict[str, Any]] = []

        if not isinstance(rag_context, dict):
            self.invalid_sources.append(
                {
                    "source_id": None,
                    "entity_type": None,
                    "entity_id": None,
                    "diagnostic": "rag_context must be a dictionary",
                    "reason": "invalid_context",
                }
            )
            return evidence_sources

        for raw_entity_type, items in rag_context.items():
            entity_type = self._normalize_entity_type(raw_entity_type)

            if not entity_type:
                self.invalid_sources.append(
                    {
                        "source_id": None,
                        "entity_type": raw_entity_type,
                        "entity_id": None,
                        "diagnostic": "entity_type is missing or empty",
                        "reason": "invalid_entity_type",
                    }
                )
                continue

            if items is None:
                continue

            if not isinstance(items, list):
                self.invalid_sources.append(
                    {
                        "source_id": None,
                        "entity_type": entity_type,
                        "entity_id": None,
                        "diagnostic": "RAG bucket must be a list",
                        "reason": "invalid_bucket",
                    }
                )
                continue

            for item in items:
                if not isinstance(item, dict):
                    self.invalid_sources.append(
                        {
                            "source_id": None,
                            "entity_type": entity_type,
                            "entity_id": None,
                            "diagnostic": "RAG source must be a dictionary",
                            "reason": "invalid_source",
                        }
                    )
                    continue

                source = self._build_source(entity_type, item)

                if source is None:
                    continue

                source_id = source["source_id"]
                existing = self.source_registry.get(source_id)

                if existing is not None:
                    conflict = self._detect_identity_conflict(
                        existing,
                        source,
                    )

                    if conflict:
                        self.invalid_sources.append(
                            {
                                "source_id": source_id,
                                "entity_type": entity_type,
                                "entity_id": source["entity_id"],
                                "diagnostic": (
                                    "duplicate source_id resolves to "
                                    "conflicting evidence identities"
                                ),
                                "reason": "duplicate_identity_conflict",
                                "conflict": conflict,
                                "existing": self._identity_view(existing),
                                "incoming": self._identity_view(source),
                            }
                        )
                        continue

                    # Same source encountered through multiple retrieval
                    # paths. Keep one canonical registry entry while
                    # retaining the strongest retrieval similarity.
                    existing_similarity = self._safe_similarity(
                        existing.get("similarity", 0.0)
                    )
                    incoming_similarity = self._safe_similarity(
                        source.get("similarity", 0.0)
                    )

                    if incoming_similarity > existing_similarity:
                        existing["similarity"] = incoming_similarity

                    continue

                self.source_registry[source_id] = source
                evidence_sources.append(source)

        return evidence_sources

    def _build_source(
        self,
        entity_type: str,
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Convert one raw RAG result into a canonical registered source.

        Identity is derived from the retrieval record itself. Metadata is
        treated as additional provenance information and is checked for
        contradictions, but is never allowed to silently redefine the
        record identity.
        """
        record_id = item.get("entity_id")

        # Do NOT use:
        #
        #   item.get("entity_id", item["id"])
        #
        # because the default expression item["id"] is evaluated eagerly
        # and can raise KeyError even when entity_id exists.
        if record_id is None:
            record_id = item.get("id")

        if record_id is None:
            self.invalid_sources.append(
                {
                    "source_id": None,
                    "entity_type": entity_type,
                    "entity_id": None,
                    "diagnostic": "source has no entity_id or id",
                    "reason": "missing_entity_id",
                }
            )
            return None

        source_id = source_id_for(entity_type, record_id)

        metadata = item.get("metadata")

        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, dict):
            self.invalid_sources.append(
                {
                    "source_id": source_id,
                    "entity_type": entity_type,
                    "entity_id": record_id,
                    "diagnostic": "source metadata must be a dictionary",
                    "reason": "invalid_metadata",
                }
            )
            return None

        metadata = deepcopy(metadata)

        metadata_entity_id = metadata.get("entity_id")

        if (
            metadata_entity_id is not None
            and not self._same_identifier(metadata_entity_id, record_id)
        ):
            self.invalid_sources.append(
                {
                    "source_id": source_id,
                    "entity_type": entity_type,
                    "entity_id": record_id,
                    "metadata_entity_id": metadata_entity_id,
                    "diagnostic": (
                        "metadata entity_id does not match "
                        "source record id"
                    ),
                    "reason": "entity_id_mismatch",
                }
            )
            return None

        metadata_entity_type = metadata.get("entity_type")

        if (
            metadata_entity_type is not None
            and self._normalize_entity_type(metadata_entity_type)
            != entity_type
        ):
            self.invalid_sources.append(
                {
                    "source_id": source_id,
                    "entity_type": entity_type,
                    "entity_id": record_id,
                    "metadata_entity_type": metadata_entity_type,
                    "diagnostic": (
                        "metadata entity_type does not match "
                        "source record type"
                    ),
                    "reason": "entity_type_mismatch",
                }
            )
            return None

        # Preserve the canonical identity in metadata so downstream
        # resolvers can inspect one consistent representation.
        metadata["entity_type"] = entity_type
        metadata["entity_id"] = record_id

        source = {
            "source_id": source_id,
            "entity_type": entity_type,
            "entity_id": record_id,
            "similarity": self._safe_similarity(
                item.get("similarity", 0.0)
            ),
            "metadata": metadata,
            "published_at": metadata.get("published_at"),
        }

        # Carry common provenance fields at the top level as well.
        #
        # These remain generic provenance concepts. Domain-specific
        # semantics are intentionally left to downstream resolvers.
        for field_name in (
            "provider",
            "source",
            "source_name",
            "company_id",
            "ticker",
            "accession_number",
            "filing_id",
            "evidence_id",
            "evidence_type",
        ):
            value = metadata.get(field_name)
            if value is not None:
                source[field_name] = value

        return source

    # ------------------------------------------------------------------
    # Claim validation
    # ------------------------------------------------------------------

    def validate_claim_evidence(
        self,
        claim: dict[str, Any],
    ) -> bool:
        """
        Backward-compatible boolean validation.

        Returns True only when every cited evidence ID resolves to a
        structurally valid registered source.

        IMPORTANT:
            True does NOT mean the source factually supports the claim.

        Domain-specific semantic validation must still be performed by
        the domain EvidenceResolver / ClaimValidator.

        For detailed diagnostics use ``resolve_claim_evidence()``.
        """
        result = self.resolve_claim_evidence(claim)
        return result["status"] == "resolved"

    def resolve_claim_evidence(
        self,
        claim: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Resolve all evidence IDs cited by a claim.

        This is the generic provenance layer.

        It verifies:

        - evidence_ids exist
        - IDs are valid strings
        - the referenced source is registered
        - the source has a coherent entity identity

        It does NOT verify:

        - metric
        - numeric value
        - reporting period
        - fiscal year/quarter
        - domain-specific factual support

        Those checks belong to the domain resolver.

        Returns a structured diagnostic result, e.g.:

            {
                "status": "resolved",
                "supported": True,
                "evidence_ids": ["news_782"],
                "resolved_sources": [...],
                "failures": [],
            }

        Missing IDs are reported explicitly instead of silently ignored.
        """
        if not isinstance(claim, dict):
            return {
                "status": "invalid",
                "supported": False,
                "evidence_ids": [],
                "resolved_sources": [],
                "failures": [
                    {
                        "evidence_id": None,
                        "reason": "invalid_claim",
                        "diagnostic": "claim must be a dictionary",
                    }
                ],
            }

        raw_evidence_ids = claim.get("evidence_ids")

        if not isinstance(raw_evidence_ids, list):
            return {
                "status": "invalid",
                "supported": False,
                "evidence_ids": [],
                "resolved_sources": [],
                "failures": [
                    {
                        "evidence_id": None,
                        "reason": "invalid_evidence_ids",
                        "diagnostic": "evidence_ids must be a list",
                    }
                ],
            }

        evidence_ids = self._normalize_evidence_ids(raw_evidence_ids)

        if not evidence_ids:
            return {
                "status": "unavailable",
                "supported": False,
                "evidence_ids": [],
                "resolved_sources": [],
                "failures": [
                    {
                        "evidence_id": None,
                        "reason": "no_evidence_ids",
                        "diagnostic": (
                            "claim does not cite any evidence IDs"
                        ),
                    }
                ],
            }

        resolved_sources: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        # Determine the claim's expected evidence types from its source block.
        # This enables type-compatibility checking: a financial_statement claim
        # should not be supported by news evidence.
        expected_evidence_types = self._expected_evidence_types(claim)

        for evidence_id in evidence_ids:
            source = self.source_registry.get(evidence_id)

            if source is None:
                failures.append(
                    {
                        "evidence_id": evidence_id,
                        "reason": "not_found",
                        "diagnostic": (
                            "cited evidence ID is not present in "
                            "the current evidence registry"
                        ),
                    }
                )
                continue

            identity_error = self._validate_registered_source(source)

            if identity_error is not None:
                failures.append(
                    {
                        "evidence_id": evidence_id,
                        **identity_error,
                    }
                )
                continue

            # Type compatibility check: the evidence entity_type should match
            # the claim's source type. A financial claim backed by news is
            # structurally invalid.
            if expected_evidence_types:
                source_entity_type = source.get("entity_type", "")
                if source_entity_type not in expected_evidence_types:
                    failures.append(
                        {
                            "evidence_id": evidence_id,
                            "reason": "evidence_type_mismatch",
                            "diagnostic": (
                                f"claim expects evidence type "
                                f"{sorted(expected_evidence_types)}, "
                                f"but cited evidence '{evidence_id}' "
                                f"has type '{source_entity_type}'"
                            ),
                        }
                    )
                    continue

            resolved_sources.append(source)

        if failures:
            return {
                "status": "invalid",
                "supported": False,
                "evidence_ids": evidence_ids,
                "resolved_sources": resolved_sources,
                "failures": failures,
            }

        # Circular-evidence guard: a claim whose resolved evidence is
        # exclusively AI-generated (previous analyses) is NOT factually
        # grounded. This keeps verdicts consistent regardless of whether
        # the LLM attached a typed source block (which already rejects
        # analysis evidence via type compatibility) or cited the evidence
        # IDs bare.
        if resolved_sources and all(
            source.get("entity_type") in self.DERIVED_EVIDENCE_TYPES
            for source in resolved_sources
        ):
            return {
                "status": "unresolved",
                "supported": False,
                "evidence_ids": evidence_ids,
                "resolved_sources": resolved_sources,
                "failures": [
                    {
                        "evidence_id": None,
                        "reason": "circular_evidence_only",
                        "diagnostic": (
                            "all cited evidence is AI-generated "
                            f"({', '.join(sorted(self.DERIVED_EVIDENCE_TYPES))}); "
                            "derived evidence cannot factually ground a claim"
                        ),
                    }
                ],
            }

        return {
            "status": "resolved",
            "supported": True,
            "evidence_ids": evidence_ids,
            "resolved_sources": resolved_sources,
            "failures": [],
        }

    # ------------------------------------------------------------------
    # Claim enrichment
    # ------------------------------------------------------------------

    def _expected_evidence_types(
        self, claim: dict[str, Any]
    ) -> set[str] | None:
        """
        Determine the expected evidence entity_types for a claim.

        Returns a set of compatible entity_type strings, or None when no
        type constraint can be inferred (in which case any evidence type
        is accepted).

        The claim's ``source`` block is inspected for a ``type`` field,
        which is mapped to compatible evidence entity_types via
        ``CLAIM_SOURCE_TYPE_COMPATIBILITY``.
        """
        source = claim.get("source")
        if not isinstance(source, dict):
            return None

        source_type = source.get("type")
        if not source_type:
            return None

        normalized_type = str(source_type).strip().lower()
        compatible = self.CLAIM_SOURCE_TYPE_COMPATIBILITY.get(normalized_type)
        if compatible is None:
            # No constraint registered for this source type.
            return None

        return compatible

    def enrich_claim_with_sources(
        self,
        claim: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Attach resolved source records to a claim.

        Unknown evidence IDs are not silently converted into valid
        evidence. They are reported under ``evidence_resolution``.
        """
        if not isinstance(claim, dict):
            return {
                "claim": claim,
                "evidence_sources": [],
                "evidence_resolution": {
                    "status": "invalid",
                    "supported": False,
                    "evidence_ids": [],
                    "resolved_sources": [],
                    "failures": [
                        {
                            "evidence_id": None,
                            "reason": "invalid_claim",
                            "diagnostic": "claim must be a dictionary",
                        }
                    ],
                },
            }

        resolution = self.resolve_claim_evidence(claim)

        return {
            **claim,
            "evidence_sources": resolution["resolved_sources"],
            "evidence_resolution": resolution,
        }

    # ------------------------------------------------------------------
    # Evidence package
    # ------------------------------------------------------------------

    def build_evidence_package(
        self,
        rag_context: RagContext,
    ) -> dict[str, Any]:
        """
        Build the complete evidence package for LLM context.

        Legacy-compatible shape:

            {
                "evidence_sources": [...],
                "source_count": N,
                "source_types": [...],
                "invalid_sources": [...]
            }

        ``source_count`` counts only valid registered sources.

        Invalid retrieval records remain available through
        ``invalid_sources`` for diagnostics and observability.
        """
        evidence_sources = self.register_sources(rag_context)

        return {
            "evidence_sources": evidence_sources,
            "source_count": len(evidence_sources),
            "source_types": sorted(
                {
                    source["entity_type"]
                    for source in evidence_sources
                }
            ),
            "invalid_sources": deepcopy(self.invalid_sources),
        }

    # ------------------------------------------------------------------
    # Registry access
    # ------------------------------------------------------------------

    def get_source_metadata(
        self,
        source_id: str,
    ) -> dict[str, Any] | None:
        """
        Return the registered source record for ``source_id`` or None.
        """
        normalized_id = self._normalize_evidence_id(source_id)

        if normalized_id is None:
            return None

        return self.source_registry.get(normalized_id)

    def get_source_identity(
        self,
        source_id: str,
    ) -> dict[str, Any] | None:
        """
        Return only provenance identity fields for a source.

        This intentionally avoids returning arbitrary evidence content.
        """
        source = self.get_source_metadata(source_id)

        if source is None:
            return None

        return self._identity_view(source)

    # ------------------------------------------------------------------
    # Internal validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_entity_type(value: Any) -> str:
        if value is None:
            return ""

        return str(value).strip().lower()

    @staticmethod
    def _normalize_evidence_id(value: Any) -> str | None:
        if value is None:
            return None

        if isinstance(value, bool):
            return None

        normalized = str(value).strip()

        return normalized or None

    def _normalize_evidence_ids(
        self,
        evidence_ids: list[Any],
    ) -> list[str]:
        """
        Normalize and deduplicate evidence IDs while preserving order.
        """
        normalized: list[str] = []
        seen: set[str] = set()

        for value in evidence_ids:
            evidence_id = self._normalize_evidence_id(value)

            if evidence_id is None:
                continue

            if evidence_id in seen:
                continue

            seen.add(evidence_id)
            normalized.append(evidence_id)

        return normalized

    @staticmethod
    def _same_identifier(
        left: Any,
        right: Any,
    ) -> bool:
        """
        Compare persisted IDs safely across int/string representations.

        Example:

            782 == "782"

        while avoiding accidental coercion of unrelated values.
        """
        if left is None or right is None:
            return left is right

        return str(left).strip() == str(right).strip()

    @staticmethod
    def _safe_similarity(value: Any) -> float:
        try:
            similarity = float(value)
        except (TypeError, ValueError):
            return 0.0

        if not isfinite(similarity):
            return 0.0

        return similarity

    def _validate_registered_source(
        self,
        source: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Validate generic source identity.

        This does not validate domain semantics.

        A source such as:

            news_782

        remains a valid *news source* here.

        Whether that news source is appropriate evidence for an SEC
        financial claim is decided downstream by the domain resolver.

        Returns:
            None when structurally valid, otherwise a diagnostic dict.
        """
        source_id = source.get("source_id")
        entity_type = source.get("entity_type")
        entity_id = source.get("entity_id")

        if not source_id:
            return {
                "reason": "missing_source_id",
                "diagnostic": "registered source has no source_id",
            }

        if not entity_type:
            return {
                "reason": "missing_entity_type",
                "diagnostic": "registered source has no entity_type",
            }

        if entity_id is None:
            return {
                "reason": "missing_entity_id",
                "diagnostic": "registered source has no entity_id",
            }

        expected_source_id = source_id_for(
            str(entity_type),
            entity_id,
        )

        if source_id != expected_source_id:
            return {
                "reason": "source_id_mismatch",
                "diagnostic": (
                    "source_id does not match the registered "
                    "entity_type/entity_id"
                ),
                "expected_source_id": expected_source_id,
                "actual_source_id": source_id,
            }

        metadata = source.get("metadata")

        if not isinstance(metadata, dict):
            return {
                "reason": "invalid_metadata",
                "diagnostic": "registered source metadata is not a dictionary",
            }

        metadata_entity_id = metadata.get("entity_id")

        if (
            metadata_entity_id is not None
            and not self._same_identifier(metadata_entity_id, entity_id)
        ):
            return {
                "reason": "entity_id_mismatch",
                "diagnostic": (
                    "metadata entity_id does not match "
                    "registered entity_id"
                ),
                "expected": entity_id,
                "actual": metadata_entity_id,
            }

        metadata_entity_type = metadata.get("entity_type")

        if (
            metadata_entity_type is not None
            and self._normalize_entity_type(metadata_entity_type)
            != self._normalize_entity_type(entity_type)
        ):
            return {
                "reason": "entity_type_mismatch",
                "diagnostic": (
                    "metadata entity_type does not match "
                    "registered entity_type"
                ),
                "expected": entity_type,
                "actual": metadata_entity_type,
            }

        return None

    # ------------------------------------------------------------------
    # Duplicate / conflict detection
    # ------------------------------------------------------------------

    def _detect_identity_conflict(
        self,
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Detect conflicting provenance identity for the same source ID.

        Returns an empty dict when there is no conflict.
        """
        conflicts: dict[str, Any] = {}

        for field_name in (
            "entity_type",
            "entity_id",
            "provider",
            "source",
            "company_id",
            "ticker",
            "accession_number",
            "filing_id",
            "evidence_type",
        ):
            existing_value = self._provenance_value(
                existing,
                field_name,
            )
            incoming_value = self._provenance_value(
                incoming,
                field_name,
            )

            # Missing information isn't a conflict. It simply means
            # the source has incomplete provenance metadata.
            if existing_value is None or incoming_value is None:
                continue

            if field_name in {"entity_id", "company_id", "filing_id"}:
                same = self._same_identifier(
                    existing_value,
                    incoming_value,
                )
            elif field_name == "entity_type":
                same = (
                    self._normalize_entity_type(existing_value)
                    == self._normalize_entity_type(incoming_value)
                )
            else:
                same = (
                    str(existing_value).strip().lower()
                    == str(incoming_value).strip().lower()
                )

            if not same:
                conflicts[field_name] = {
                    "existing": existing_value,
                    "incoming": incoming_value,
                }

        return conflicts

    @staticmethod
    def _provenance_value(
        source: dict[str, Any],
        field_name: str,
    ) -> Any:
        if field_name in source:
            return source.get(field_name)

        metadata = source.get("metadata")

        if isinstance(metadata, dict):
            return metadata.get(field_name)

        return None

    @staticmethod
    def _identity_view(
        source: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Return a safe, provenance-only representation.

        Do not expose arbitrary source content when the caller only needs
        identity.
        """
        metadata = source.get("metadata")

        if not isinstance(metadata, dict):
            metadata = {}

        identity: dict[str, Any] = {
            "source_id": source.get("source_id"),
            "entity_type": source.get("entity_type"),
            "entity_id": source.get("entity_id"),
        }

        for field_name in (
            "provider",
            "source",
            "source_name",
            "company_id",
            "ticker",
            "accession_number",
            "filing_id",
            "evidence_id",
            "evidence_type",
            "published_at",
        ):
            value = source.get(field_name)

            if value is None:
                value = metadata.get(field_name)

            if value is not None:
                identity[field_name] = value

        return identity