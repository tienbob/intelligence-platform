"""
Generic LLM core — the framework's language-model engine.

The framework owns HOW to talk to models (OpenAI-compatible transport,
JSON mode, token accounting, structured-output recovery). Domains own
WHAT to ask (prompt templates, schemas, validation rules).

    Domain prompt + context
          ↓
    LLMClient.chat_json()   ← this package
          ↓
    Parsed JSON + usage metadata
"""

from app.intelligence.llm.client import LLMClient
from app.intelligence.llm.structured_output import extract_json

__all__ = ["LLMClient", "extract_json"]
