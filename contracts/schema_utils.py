"""
schema_utils.py -- generic structural validation shared by every D8 step-contract.

D8 (docs/DECISIONS.md) requires that any LLM-touching step have an *identical*
input/output contract whether it runs through an agentic harness (chunk 3.2) or
a human copy-pasting into a chat LLM (chunk 3.3/3.4): the same validator must
accept or reject output from either source with no special-casing. This module
is that shared validator -- domain-agnostic, so the first concrete contract
(lint/vision_review_contract.py, chunk 3.1) and any later one (persona-review,
etc.) both build on it instead of hand-rolling their own checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: type
    required: bool = True
    description: str = ""
    allowed_values: tuple[Any, ...] | None = None
    item_schema: "list[FieldSpec] | None" = None  # for list-of-dict fields; data, not a
    # closure, so a doc generator (contracts/init_ai.py) can introspect the nested
    # shape instead of only the validator being able to check it.


def validate(obj: Any, schema: list[FieldSpec]) -> list[str]:
    """Structural validation of `obj` against a FieldSpec list. Returns error
    strings; empty list means valid. Used identically for input assembly
    (self-check) and output verification (harness or copy-paste result)."""
    if not isinstance(obj, dict):
        return [f"top-level value must be an object/dict, got {type(obj).__name__}"]

    errors: list[str] = []
    for spec in schema:
        if spec.name not in obj:
            if spec.required:
                errors.append(f"missing required field '{spec.name}'")
            continue
        value = obj[spec.name]
        if not isinstance(value, spec.type):
            errors.append(f"field '{spec.name}' must be {spec.type.__name__}, got {type(value).__name__}")
            continue
        if spec.allowed_values is not None and value not in spec.allowed_values:
            errors.append(f"field '{spec.name}'={value!r} not in allowed values {spec.allowed_values}")
        if spec.item_schema is not None and isinstance(value, list):
            for i, item in enumerate(value):
                errors.extend(f"{spec.name}[{i}]: {e}" for e in validate(item, spec.item_schema))
    return errors
