"""
Domain Packs — self-contained intelligence modules.

Each subdirectory is a domain pack that plugs into the core intelligence engine.
A domain pack must contain a manifest.py that exports a DOMAIN instance
implementing the DomainModule protocol.

To add a new domain:
    1. Create domains/<name>/
    2. Implement manifest.py with a DOMAIN instance
    3. Set INTELLIGENCE_DOMAINS=stock,<name> (or omit to enable all)
    4. Restart — the registry auto-discovers it
"""