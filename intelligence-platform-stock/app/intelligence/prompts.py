"""
Prompt Registry — the framework's prompt-management primitive.

A domain's ``get_prompts()`` returns a ``PromptRegistry`` rather than a raw
dict. This gives prompts identity, metadata, and formatting behavior while
staying trivially simple (a dict-backed implementation is provided).

The framework never inspects prompt *content* — it only looks prompts up
by name and passes them to the LLM service.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PromptRegistry(Protocol):
    """Read-only registry of named prompt templates."""

    def get(self, name: str, default: str = "") -> str:
        """Return the prompt registered under ``name``, or ``default``."""
        ...

    def names(self) -> list[str]:
        """Return all registered prompt names."""
        ...


class SimplePromptRegistry:
    """
    Dict-backed PromptRegistry implementation.

    Domains can use this directly::

        def get_prompts(self) -> PromptRegistry:
            return SimplePromptRegistry({
                "company": Path("prompts/company.txt").read_text(),
                "default": "You are an expert analyst.",
            })

    or subclass it to add lazy loading / templating.
    """

    def __init__(self, prompts: dict[str, str] | None = None):
        self._prompts: dict[str, str] = dict(prompts or {})

    def get(self, name: str, default: str = "") -> str:
        return self._prompts.get(name, default)

    def names(self) -> list[str]:
        return sorted(self._prompts.keys())

    def register(self, name: str, content: str) -> None:
        """Register (or replace) a prompt. Intended for domain setup code."""
        self._prompts[name] = content

    def __contains__(self, name: str) -> bool:
        return name in self._prompts

    def __len__(self) -> int:
        return len(self._prompts)
