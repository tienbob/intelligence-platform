"""
Example Domain — minimal domain proving the core is domain-neutral.

This domain analyzes "products" with a trivial scoring model.
It exists to prove that the intelligence platform works with ANY domain,
not just stock/investment.

To test: INTELLIGENCE_DOMAINS=example
"""

from __future__ import annotations

from typing import Any

DOMAIN_NAME = "example"
DOMAIN_VERSION = "1.0"


class ExampleDomain:
    """Minimal example domain for platform validation."""

    name = DOMAIN_NAME
    version = DOMAIN_VERSION

    def get_providers(self) -> dict[str, Any]:
        from app.domains.example.providers import ProductProvider
        return {"product_db": ProductProvider()}

    def get_normalizers(self) -> dict[str, Any]:
        from app.domains.example.normalization import ProductNormalizer
        return {"product": ProductNormalizer()}

    def get_context_builder(self) -> Any:
        from app.domains.example.context_builder import ExampleContextBuilder
        return ExampleContextBuilder()

    def get_scoring_strategy(self) -> Any:
        from app.domains.example.scoring import ExampleScoringStrategy
        return ExampleScoringStrategy()

    def get_intelligence_tasks(self) -> list[Any]:
        return []  # No background tasks for example domain

    def get_api_router(self):
        from app.domains.example.api import example_router
        return example_router

    def get_prompts(self) -> PromptRegistry:
        from pathlib import Path

        from app.intelligence.prompts import SimplePromptRegistry

        prompts_dir = Path(__file__).parent / "prompts"
        registry = SimplePromptRegistry()
        for prompt_file in prompts_dir.glob("*.txt"):
            registry.register(prompt_file.stem, prompt_file.read_text())
        return registry


DOMAIN = ExampleDomain()