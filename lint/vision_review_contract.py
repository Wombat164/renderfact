"""
vision_review_contract.py -- D8 I/O contract for the vision-review step (chunk 3.1).

lint/svg_metrics.py already draws the line this step fills: it is a
"deterministic visual-QA layer" that explicitly "complements (does not
replace) the vision-reviewer 6th-role agent option for subjective layout
review." That vision-reviewer was gestured at but never built. This module
defines its contract -- chunk 3.1's whole scope -- so both modes
produce output no downstream consumer can tell apart:

  - harness mode (chunk 3.2, `render init-ai`)        -- shipped
  - copy-paste mode (chunk 3.4, `render copy-paste`)  -- shipped

Both modes call assemble_input() for the same deterministic context
(the PaperBanana "vision + spec dual-context" trick, see
docs/prior-art-paperbanana-prompt-patterns.md: give the reviewer the image
AND the hard numbers, never vision alone) and validate_output() against the
same schema.
"""

from __future__ import annotations

from pathlib import Path

from contracts.schema_utils import FieldSpec, validate

TASK_INTENT = (
    "Assess this rendered diagram for subjective layout quality that "
    "geometry-based metrics cannot capture: visual hierarchy (does the eye "
    "land on the right element first), legend/label clutter, whether the "
    "flow direction reads naturally, and whether the diagram communicates "
    "its intended message at the stated view-tier. Deterministic metrics "
    "(edge crossings, node overlap, whitespace, palette/contrast/a11y) are "
    "provided as context -- do not re-derive them, judge what they miss."
)

VALID_TIERS = (
    "executive-cover",
    "programme-planning",
    "operator-handoff",
    "procurement-annex",
)

_FINDING_SCHEMA: list[FieldSpec] = [
    FieldSpec("criterion", str, required=True,
              description="e.g. visual-hierarchy, legend-clarity, label-legibility, flow-readability"),
    FieldSpec("severity", str, required=True, allowed_values=("info", "warn", "block"),
              description="Per-finding severity."),
    FieldSpec("comment", str, required=True, description="One sentence, specific."),
]

INPUT_SCHEMA: list[FieldSpec] = [
    FieldSpec("task_intent", str, required=True,
              description="Fixed instruction text (see TASK_INTENT) -- what judgment is wanted."),
    FieldSpec("rendered_image_path", str, required=True,
              description="Path to the rendered diagram image (PNG preferred -- pasteable/viewable "
                          "in any chat LLM UI; SVG accepted if PNG unavailable)."),
    FieldSpec("tier", str, required=True, allowed_values=VALID_TIERS,
              description="View-tier the diagram was rendered for; sets the review's strictness lens."),
    FieldSpec("deterministic_metrics", dict, required=True,
              description="svg_metrics.py + visual_quality.py results for the same file."),
]

OUTPUT_SCHEMA: list[FieldSpec] = [
    FieldSpec("status", str, required=True, allowed_values=("OK", "WARN", "BLOCK"),
              description="Overall verdict -- same three-state vocabulary as visual_quality.py."),
    FieldSpec("findings", list, required=True,
              description="Per-criterion findings.",
              item_schema=_FINDING_SCHEMA),
    FieldSpec("summary", str, required=True, description="One-paragraph human-readable verdict."),
    FieldSpec("reviewer_mode", str, required=True, allowed_values=("harness", "copy-paste"),
              description="Which D8 mode produced this output -- provenance, not a quality signal."),
]


def assemble_input(rendered_image_path: Path | str, tier: str, deterministic_metrics: dict) -> dict:
    """Deterministic input assembly -- identical regardless of which mode consumes it.
    Raises ValueError if the assembled object would fail its own schema."""
    obj = {
        "task_intent": TASK_INTENT,
        "rendered_image_path": str(rendered_image_path),
        "tier": tier,
        "deterministic_metrics": deterministic_metrics,
    }
    errors = validate(obj, INPUT_SCHEMA)
    if errors:
        raise ValueError(f"assembled input failed its own schema: {errors}")
    return obj


def validate_output(obj: dict) -> tuple[bool, list[str]]:
    """Validate a vision-review result -- from EITHER mode -- against the fixed output schema."""
    errors = validate(obj, OUTPUT_SCHEMA)
    return len(errors) == 0, errors
