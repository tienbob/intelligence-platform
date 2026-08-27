"""Explicit version identities used in API and analysis metadata.

These values describe different compatibility surfaces and must not be
collapsed into a single ambiguous ``version`` field.

Version label map — one owner per label:

=======================  ====================================  ==========================
Label                    Owner (source of truth)               Surfaced by
application_version      settings.APP_VERSION (env-tunable)    FastAPI() + ``GET /``
architecture_version     ARCHITECTURE_VERSION (this module)    ``GET /``
pipeline_version         PIPELINE_VERSION (this module)        AnalysisResult.metadata,
                                                               ``GET /``
domain_version           DomainModule.version (per-domain      ``GET /domains``, pipeline
                         manifest, e.g. stock DOMAIN_VERSION)  metadata
scoring_version          Stock config ``SCORING_VERSION``      scoring provenance
prompt_version           Stock manifest ``PROMPT_VERSION``     prompt provenance
=======================  ====================================  ==========================

Framework-level labels live here; domain/scoring/prompt versions intentionally
live with their owners (V3 §19) so domains version independently.
"""

ARCHITECTURE_VERSION = "3.0"
PIPELINE_VERSION = "3.0"
