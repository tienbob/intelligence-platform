"""
Structured-output extraction — recovering JSON from imperfect LLM text.

Handles markdown code fences and surrounding prose. Falls back to a
``raw_response`` dict when no JSON object can be recovered.
"""

from __future__ import annotations

import json
from typing import Any


def extract_json(content: str | None) -> dict[str, Any]:
    """Extract a JSON object from an LLM response that isn't pure JSON.

    Handles markdown code fences (```json ... ```) and surrounding prose.
    Falls back to a raw_response dict if no JSON can be extracted.
    """
    if not content:
        return {"raw_response": ""}
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"raw_response": content}
