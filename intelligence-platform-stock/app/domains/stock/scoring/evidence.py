"""
Stock evidence attribution (Section 32, Section 50).

The generic claim↔source attribution mechanics now live in
``app.intelligence.evidence``. This module is a thin Stock re-export so
existing Stock callers keep the same ``EvidenceAttributor`` API with a
to the framework's generic implementation.
"""

from __future__ import annotations

from app.intelligence.evidence.attribution import EvidenceAttributor

__all__ = ["EvidenceAttributor"]