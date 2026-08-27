"""
Generic RAG core — the framework's retrieval engine.

The framework owns HOW to retrieve:
    embedding preparation, pgvector similarity search, keyword search,
    metadata filtering, merging, deduplication, ranking.

Domains own WHAT to retrieve:
    document buckets, entity semantics, threshold policies.

    Stock RAG Context                HR RAG Context (future)
         │                                │
   ┌─────┼─────┬──────┐              ┌────┼────┬────────┐
   ▼     ▼     ▼      ▼              ▼    ▼    ▼        ▼
  news filings events analyses    candidates reviews job posts
   └─────┴─────┴──────┘              └────┴────┴────────┘
                   │                        │
                   └────────┬───────────────┘
                            ▼
                 GenericRAGService (this package)
                            ▼
                       pgvector
"""

from app.intelligence.rag.filters import build_filter_sql
from app.intelligence.rag.ranking import deduplicate, merge_results, rank_results
from app.intelligence.rag.retrieval import (
    keyword_search,
    prepare_query_embedding,
    similarity_search,
)
from app.intelligence.rag.service import GenericRAGService, build_filters
from app.intelligence.rag.types import RetrievedDocument, RetrievalFilters

__all__ = [
    "GenericRAGService",
    "RetrievedDocument",
    "RetrievalFilters",
    "build_filter_sql",
    "build_filters",
    "deduplicate",
    "keyword_search",
    "merge_results",
    "prepare_query_embedding",
    "rank_results",
    "similarity_search",
]