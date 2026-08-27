"""
Framework tests: architectural purity (Phase 12, §12.1–12.5).

Enforces at source level:
  - app/intelligence/** never imports any app.domains.* module (§12.1)
  - the pipeline never references domain identifiers like ticker /
    company_id (§12.3)
  - Evidence objects are only constructed through the framework evidence
    core inside the pipeline (§12.4)
  - app/intelligence/validation contains no investment-domain concepts
    (§12.5)

Together with ``IntelligencePipeline()`` being constructible without
Stock/DB/API keys, this locks the framework/domain boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_DIR = ROOT / "app" / "intelligence"


def _framework_sources():
    return sorted(FRAMEWORK_DIR.rglob("*.py"))


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


# ── §12.1 No domain leakage into the framework ───────────────────

def test_framework_never_imports_domain_code():
    offenders = []
    for src in _framework_sources():
        if any(part in {"__pycache__"} for part in src.parts):
            continue
        text = src.read_text()
        for needle in (
            "from app.domains",
            "import app.domains",
            "app . domains",
        ):
            if needle in text:
                offenders.append(f"{_rel(src)}: contains '{needle}'")
    assert not offenders, "domain leakage:\n" + "\n".join(offenders)


def test_framework_imports_work_without_domains_loaded():
    """
    Verify in a CLEAN subprocess that all framework modules import with
    zero domain modules present (and remain absent afterwards).

    Runs isolated because mutating sys.modules of a shared pytest process
    would poison unrelated tests.
    """
    import subprocess

    code = (
        "import sys;"
        "mods = ["
        "'app.intelligence.pipeline',"
        "'app.intelligence.llm',"
        "'app.intelligence.rag',"
        "'app.intelligence.embeddings',"
        "'app.intelligence.evidence',"
        "'app.intelligence.validation',"
        "'app.intelligence.entity_resolution',"
        "'app.intelligence.providers',"
        "'app.intelligence.observations',"
        "'app.intelligence.prompts',"
        "'app.intelligence.contracts',"
        "'app.intelligence.registry',"
        "]"
        "+ ['app.intelligence.llm.client', 'app.intelligence.rag.retrieval']"
        ";import importlib;"
        "[importlib.import_module(m) for m in mods];"
        "leaked = [m for m in sys.modules if m.startswith('app.domains')];"
        "assert not leaked, f'domain modules imported: {leaked}';"
        "print('CLEAN_IMPORT_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={
            "PYTHONPATH": str(ROOT),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(ROOT),
        },
    )
    # Import failure OR domain leakage both fail the check.
    assert "CLEAN_IMPORT_OK" in proc.stdout, (
        f"framework import check failed:\nstdout={proc.stdout[-500:]}\n"
        f"stderr={proc.stderr[-800:]}"
    )


def _strip_docstrings(source: str) -> str:
    """Remove triple-quoted strings so prose doesn't trip code scans."""
    import re

    return re.sub(r'""".*?"""', '""', source, flags=re.DOTALL)


# ── §12.3 Pipeline never speaks domain identifiers ───────────────

def test_pipeline_has_no_domain_identifiers():
    src = _strip_docstrings((FRAMEWORK_DIR / "pipeline.py").read_text())
    for bad in ("ticker", "company_id", "stock_id"):
        assert bad not in src.replace("entity_id", ""), (
            f"pipeline references domain identifier '{bad}'"
        )


# ── §12.4 Evidence built via framework core only ─────────────────

def test_pipeline_does_not_construct_evidence_directly():
    src = (FRAMEWORK_DIR / "pipeline.py").read_text()
    assert "Evidence(" not in src, (
        "pipeline constructs Evidence inline; use observations_to_evidence"
    )


def test_observations_module_is_the_single_evidence_factory():
    # observations_to_evidence must be THE conversion used everywhere.
    obs_src = (FRAMEWORK_DIR / "observations.py").read_text()
    assert "Evidence(" in obs_src
    svc_src = str((FRAMEWORK_DIR / "evidence" / "service.py").read_text())
    assert "observations_to_evidence" in svc_src


# ── §12.5 Validation package stays domain-neutral ────────────────

def test_validation_package_has_no_investment_concepts():
    offenders = []
    vdir = FRAMEWORK_DIR / "validation"
    for src in sorted(vdir.glob("*.py")):
        text = src.read_text().lower()
        for concept in (
            "investment",
            "ticker",
            "bull_case",
            "bear_case",
            "portfolio",
            "financial",
            "stock",
        ):
            if concept in text:
                offenders.append(
                    f"{_rel(src)}: contains '{concept}'"
                )
    assert not offenders, "domain concepts leaked into validation:\n" + "\n".join(offenders)
