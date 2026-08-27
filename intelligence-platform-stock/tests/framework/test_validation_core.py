"""
Framework tests: generic validation core.

Verifies the framework's schema/structural validation primitive layer is
generic and correct — required fields, type checks, confidence bounds,
enum membership, schema conformance, and repair. No domain imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.intelligence.validation import (  # noqa: E402
    ValidationResult,
    ValidationService,
    collect,
    require_fields,
    require_list_of_dict,
    validate_confidence,
    validate_in,
)
from app.intelligence.validation.service import SchemaValidator  # noqa: E402


def test_require_fields_returns_issues():
    issues = require_fields({"a": 1}, ["a", "b"])
    assert any("b" in i.message for i in issues)
    assert not any(i.field == "a" for i in issues)


def test_validate_confidence_bounds():
    assert validate_confidence(0.5) == []
    assert validate_confidence(1.0) == []
    assert len(validate_confidence(1.5)) == 1
    assert len(validate_confidence(-0.1)) == 1
    assert validate_confidence(None) == []
    assert len(validate_confidence("oops")) == 1


def test_validate_in_membership():
    assert validate_in("high", {"low", "medium", "high"}, field_name="impact") == []
    assert len(validate_in("critical", {"low", "medium", "high"}, field_name="impact")) == 1


def test_require_list_of_dict():
    assert require_list_of_dict({"causes": [{"a": 1}]}, "causes") == []
    assert len(require_list_of_dict({"causes": "notalist"}, "causes")) == 1
    assert len(require_list_of_dict({"causes": "x"}, "causes")) == 1


def test_schema_validator_conformance():
    sv = SchemaValidator()
    ok = sv.validate({"summary": "x", "causes": []}, {"summary": "str", "causes": "list"})
    assert ok.is_valid
    bad = sv.validate({"summary": "x", "causes": "no"}, {"summary": "str", "causes": "list"})
    assert not bad.is_valid
    missing = sv.validate({"summary": "x"}, {"summary": "str", "risks": "list"})
    assert any("risks" in i.field for i in missing.issues)


def test_schema_validator_type_tags():
    sv = SchemaValidator()
    assert sv.validate({"a": 1}, {"a": "int"}).is_valid
    assert sv.validate({"a": 1.5}, {"a": "int"}).is_valid is False
    assert sv.validate({"a": 1.5}, {"a": "number"}).is_valid


def test_validation_service_repairs_missing_required():
    import asyncio

    svc = ValidationService()
    output = asyncio.run(
        svc.validate({"insights": []}, domain="stock", analysis_type="company")
    )
    assert "summary" in output  # repaired in
    assert output["_validation"]["status"] == "repaired"


def test_validation_service_wraps_non_dict():
    import asyncio

    svc = ValidationService()
    output = asyncio.run(svc.validate("just a string"))
    assert output["_validation"]["status"] == "wrapped"


def test_validation_service_validate_schema():
    import asyncio

    svc = ValidationService()
    ok = asyncio.run(
        svc.validate_schema({"summary": "s"}, {"summary": "str"})
    )
    assert ok == (True, [])
    bad = asyncio.run(
        svc.validate_schema({"summary": 123}, {"summary": "str"})
    )
    assert bad[0] is False


def test_validation_result_api():
    from app.intelligence.validation.types import ValidationIssue

    r = ValidationResult()
    assert r.is_valid
    r2 = ValidationResult(issues=[ValidationIssue("confidence", "out of bounds")])
    assert not r2.is_valid
    assert r2.error_messages()


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print("ALL PASS" if failures == 0 else f"{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)