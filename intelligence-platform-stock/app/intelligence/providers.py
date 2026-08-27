"""
Provider capability toolkit — framework-level conformance.

The framework defines WHAT a capability means (the protocols in
``app.intelligence.contracts``). Domains decide WHICH capabilities each
vendor provider offers, either by naturally conforming (duck-typing the
protocol methods) or by wrapping vendors in thin capability adapters
(see ``app/domains/stock/providers/capabilities.py``).

This module is the generic way to ask: "what can this provider do?" and
"does this provider satisfy this capability?" without importing domain
code.
"""

from __future__ import annotations

from typing import Any

from app.intelligence.contracts import (
    EntityDataProvider,
    NewsProvider,
    SearchProvider,
    TimeSeriesProvider,
)

__all__ = [
    "CAPABILITY_PROTOCOLS",
    "EntityDataProvider",
    "NewsProvider",
    "SearchProvider",
    "TimeSeriesProvider",
    "framework_capabilities",
    "has_capability",
]

# framework capability name → its protocol. Single source of truth used by
# the conformance helpers below and by the capability adapters in domains.
CAPABILITY_PROTOCOLS: dict[str, type] = {
    "entity_data": EntityDataProvider,
    "time_series": TimeSeriesProvider,
    "news": NewsProvider,
    "search": SearchProvider,
}


def framework_capabilities(provider: Any) -> set[str]:
    """
    Return the set of framework capability names a provider satisfies.

    Detection order:
      1. Declaration: a ``capabilities`` or ``framework_capabilities``
         attribute (set/list) the provider or its adapter declares
         explicitly. This is authoritative — capability adapters declare
         what their vendor truly offers even though the shared base class
         also defines every generic method signature.
      2. Duck-type: ``isinstance`` against the runtime-checkable capability
         protocols (checks the provider exposes the protocol's methods).
         Only used when no explicit declaration is present, so natural
         conforming providers are detected for free.

    Note: duck-typing is intentionally NOT unioned with declarations. A
    shared base class (like Stock's ``CapabilityAdapter``) that defines all
    generic signatures would otherwise make every adapter "match" every
    capability it does not actually offer.
    """
    declared = getattr(provider, "capabilities", None)
    if declared is None or not isinstance(declared, (set, frozenset, list, tuple)):
        declared = getattr(provider, "framework_capabilities", None)

    if declared is not None and isinstance(declared, (set, frozenset, list, tuple)):
        declared_set = set(declared)
        # Keep only capabilities that are real framework capabilities.
        return declared_set & set(CAPABILITY_PROTOCOLS)

    # No explicit declaration → fall back to structural duck-typing.
    result: set[str] = set()
    for name, protocol in CAPABILITY_PROTOCOLS.items():
        try:
            if isinstance(provider, protocol):
                result.add(name)
        except TypeError:
            # runtime_checkable protocol inspection can raise for unusual
            # objects (e.g. some proxied classes). Treat as not matching.
            pass
    return result


def has_capability(provider: Any, capability: str) -> bool:
    """Whether a provider satisfies the named capability."""
    return capability in framework_capabilities(provider)