"""
Generic embedding core — the framework's vector-production engine.

The framework owns HOW embeddings are made and stored:
    provider client abstraction, batching with per-item fallback,
    retry/backoff, pgvector persistence, dimension validation,
    dedup filtering.

Domains own WHAT gets embedded and WHEN:
    content selection, bucket semantics, domain metadata.

    Stock ingestion workers            HR ingestion (future)
      "embed this news/event/analysis"  "embed this candidate/review"
                │                              │
                └──────────────┬───────────────┘
                               ▼
                 GenericEmbeddingService (this package)
                               ▼
                        embedding provider
                               ▼
                          pgvector table
"""

from app.intelligence.embeddings.batching import embed_batch_with_fallback
from app.intelligence.embeddings.client import (
    SUPPORTED_PROVIDERS,
    EmbeddingClient,
)
from app.intelligence.embeddings.persistence import (
    PgVectorStore,
    to_pgvector,
    unembedded_filter,
)
from app.intelligence.embeddings.service import (
    GenericEmbeddingService,
    build_generic_service,
)
from app.intelligence.embeddings.types import VectorRecord, chunked

__all__ = [
    "EmbeddingClient",
    "GenericEmbeddingService",
    "PgVectorStore",
    "SUPPORTED_PROVIDERS",
    "VectorRecord",
    "build_generic_service",
    "chunked",
    "embed_batch_with_fallback",
    "to_pgvector",
    "unembedded_filter",
]