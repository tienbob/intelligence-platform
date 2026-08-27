"""
Core Intelligence Engine — domain-agnostic AI research pipeline.

This package contains the reusable framework that any domain (stock, HR,
legal, real estate, etc.) plugs into. It knows HOW to run intelligence;
the domain knows WHAT intelligence means.

Pipeline:
    Request → Domain Resolver → Ingestion → Normalization →
    Entity Resolution → Evidence Collection → RAG Retrieval →
    Context Builder → LLM → Structured Validation →
    Domain Scoring → Result
"""