"""
Generic evidence core — the framework's provenance/attribution engine.

The framework owns HOW claims are traced to sources (observation
boundary, source registry, claim enrichment, evidence packages).
Domains own WHAT counts as meaningful evidence for their analysis.

    Vendor response
          ↓
    Observation
          ↓
    Evidence          ← this package
          ↓
    claim ↔ source    ← EvidenceAttributor
"""

from app.intelligence.evidence.attribution import EvidenceAttributor
from app.intelligence.evidence.service import EvidenceService
from app.intelligence.evidence.types import (
    EvidencePackage,
    EvidenceSource,
    RagContext,
    source_id_for,
)

__all__ = [
    "EvidenceAttributor",
    "EvidencePackage",
    "EvidenceService",
    "EvidenceSource",
    "RagContext",
    "source_id_for",
]