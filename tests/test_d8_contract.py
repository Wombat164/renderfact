"""
Tests for the D8 I/O contract (chunk 3.1): contracts/schema_utils.py (generic
validator) + lint/vision_review_contract.py (first concrete instantiation).

Covers: the generic validator's pass/fail behaviour on required/typed/
allowed-value/nested-list fields, and that the vision-review contract's
assemble_input()/validate_output() actually enforce their own schemas --
the property D8 depends on (harness output and copy-paste output must be
judged by the identical rule).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lint"))

from contracts.schema_utils import FieldSpec, validate  # noqa: E402
import vision_review_contract as vrc  # noqa: E402


def test_validate_accepts_well_formed_object():
    schema = [FieldSpec("name", str), FieldSpec("count", int, required=False)]
    assert validate({"name": "x", "count": 3}, schema) == []
    assert validate({"name": "x"}, schema) == []  # optional field omitted is fine


def test_validate_rejects_missing_required_field():
    schema = [FieldSpec("name", str)]
    errors = validate({}, schema)
    assert any("missing required field 'name'" in e for e in errors)


def test_validate_rejects_wrong_type():
    schema = [FieldSpec("count", int)]
    errors = validate({"count": "not-an-int"}, schema)
    assert any("must be int" in e for e in errors)


def test_validate_rejects_disallowed_value():
    schema = [FieldSpec("status", str, allowed_values=("OK", "WARN", "BLOCK"))]
    errors = validate({"status": "MAYBE"}, schema)
    assert any("not in allowed values" in e for e in errors)


def test_validate_rejects_non_dict_top_level():
    errors = validate(["not", "a", "dict"], [FieldSpec("name", str)])
    assert len(errors) == 1


def test_validate_recurses_into_list_items():
    item_schema = [FieldSpec("id", str)]
    schema = [FieldSpec("items", list, item_schema=item_schema)]
    errors = validate({"items": [{"id": "a"}, {}]}, schema)
    assert any("items[1]" in e and "missing required field 'id'" in e for e in errors)


def test_assemble_input_produces_schema_valid_object():
    obj = vrc.assemble_input("renders/hero.png", "operator-handoff", {"edge_crossings": 0})
    assert validate(obj, vrc.INPUT_SCHEMA) == []
    assert obj["task_intent"] == vrc.TASK_INTENT


def test_assemble_input_rejects_bad_tier():
    with pytest.raises(ValueError, match="tier"):
        vrc.assemble_input("renders/hero.png", "not-a-real-tier", {})


def test_validate_output_accepts_well_formed_result():
    result = {
        "status": "WARN",
        "findings": [
            {"criterion": "legend-clarity", "severity": "warn", "comment": "legend overlaps node C."},
        ],
        "summary": "Mostly clear; legend placement needs adjustment.",
        "reviewer_mode": "harness",
    }
    ok, errors = vrc.validate_output(result)
    assert ok, errors


def test_validate_output_rejects_missing_finding_field():
    result = {
        "status": "OK",
        "findings": [{"criterion": "flow-readability", "severity": "info"}],  # missing comment
        "summary": "Clear.",
        "reviewer_mode": "copy-paste",
    }
    ok, errors = vrc.validate_output(result)
    assert not ok
    assert any("findings[0]" in e and "comment" in e for e in errors)


def test_validate_output_rejects_bad_status():
    result = {
        "status": "PERFECT",
        "findings": [],
        "summary": "x",
        "reviewer_mode": "harness",
    }
    ok, errors = vrc.validate_output(result)
    assert not ok
    assert any("status" in e for e in errors)


def test_validate_output_rejects_unknown_reviewer_mode():
    result = {
        "status": "OK",
        "findings": [],
        "summary": "x",
        "reviewer_mode": "telepathy",
    }
    ok, errors = vrc.validate_output(result)
    assert not ok
    assert any("reviewer_mode" in e for e in errors)
