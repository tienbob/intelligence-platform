"""
Domain Registry — discovers, validates, and manages domain modules.

The registry is the central mechanism that makes the platform domain-agnostic.
main.py and scheduler.py use the registry to auto-discover domains without
importing domain-specific code.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.intelligence.contracts import DomainModule

logger = get_logger(__name__)

# Path to the domains directory
DOMAINS_DIR = Path(__file__).parent.parent / "domains"

# Environment variable to enable/disable domains
# Format: INTELLIGENCE_DOMAINS=stock,hr,legal
# If not set, all discovered domains are enabled.
_ENABLED_DOMAINS_ENV = "INTELLIGENCE_DOMAINS"


class DomainRegistry:
    """
    Discovers and manages domain modules.

    Usage:
        registry = DomainRegistry()
        registry.discover()

        for domain in registry.enabled:
            app.include_router(domain.get_api_router())
    """

    def __init__(self, domains_dir: Path | None = None):
        self._domains_dir = domains_dir or DOMAINS_DIR
        self._domains: dict[str, DomainModule] = {}
        self._discovered = False

    @property
    def enabled(self) -> list[DomainModule]:
        """Return all enabled domain modules."""
        if not self._discovered:
            self.discover()
        enabled_names = self._get_enabled_names()
        return [
            domain
            for name, domain in self._domains.items()
            if name in enabled_names
        ]

    @property
    def all(self) -> dict[str, DomainModule]:
        """Return all discovered domains (including disabled)."""
        if not self._discovered:
            self.discover()
        return dict(self._domains)

    def discover(self) -> None:
        """
        Scan the domains/ directory and load all domain modules.

        Each subdirectory of domains/ that contains a manifest.py
        is treated as a domain pack.
        """
        if not self._domains_dir.exists():
            logger.warning("Domains directory not found: %s", self._domains_dir)
            self._discovered = True
            return

        self._domains.clear()

        for entry in sorted(self._domains_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue

            manifest_path = entry / "manifest.py"
            if not manifest_path.exists():
                logger.debug(
                    "Skipping %s — no manifest.py found", entry.name
                )
                continue

            try:
                domain = self._load_domain(entry.name)
                if domain is not None:
                    self._domains[entry.name] = domain
                    logger.info(
                        "Discovered domain: %s v%s", domain.name, domain.version
                    )
            except Exception as exc:
                logger.error(
                    "Failed to load domain '%s': %s", entry.name, exc
                )

        self._discovered = True
        logger.info(
            "Domain discovery complete: %d domain(s) found (%d enabled)",
            len(self._domains),
            len(self.enabled),
        )

    def get(self, name: str) -> DomainModule | None:
        """Get a domain module by name."""
        if not self._discovered:
            self.discover()
        return self._domains.get(name)

    def is_enabled(self, name: str) -> bool:
        """Check if a domain is enabled."""
        return name in self._get_enabled_names() and name in self._domains

    def _load_domain(self, name: str) -> DomainModule | None:
        """Load a domain module from its manifest."""
        module_path = f"app.domains.{name}.manifest"
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            logger.error("Cannot import %s: %s", module_path, exc)
            return None

        # Look for the domain instance (convention: DOMAIN or domain)
        domain = getattr(module, "DOMAIN", None) or getattr(module, "domain", None)
        if domain is None:
            logger.error(
                "Domain '%s' manifest has no DOMAIN or domain export", name
            )
            return None

        # Basic validation
        if not hasattr(domain, "name") or not hasattr(domain, "version"):
            logger.error("Domain '%s' is missing required attributes", name)
            return None

        return domain

    def _get_enabled_names(self) -> set[str]:
        """Get the set of enabled domain names from environment."""
        env_val = os.environ.get(_ENABLED_DOMAINS_ENV, "").strip()
        if not env_val:
            # All discovered domains are enabled by default
            return set(self._domains.keys())
        return {name.strip() for name in env_val.split(",") if name.strip()}


# Global singleton
_registry: DomainRegistry | None = None


def get_registry() -> DomainRegistry:
    """Get the global domain registry singleton."""
    global _registry
    if _registry is None:
        _registry = DomainRegistry()
        _registry.discover()
    return _registry


def reset_registry() -> None:
    """Reset the registry (useful for testing)."""
    global _registry
    _registry = None