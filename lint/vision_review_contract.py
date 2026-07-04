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

import sys
from pathlib import Path

from contracts.schema_utils import FieldSpec, validate

# D16 fuzzy-gate: run the deterministic metrics FIRST, escalate the vision LLM
# only past a confidence threshold (see docs/DECISIONS.md D16 + the Track G plan).
DEFAULT_THRESHOLD = 0.6

TASK_INTENT = (
    "Assess this rendered diagram for subjective layout quality that "
    "geometry-based metrics cannot capture: visual hierarchy (does the eye "
    "land on the right element first), legend/label clutter, whether the "
    "flow direction reads naturally, and whether the diagram communicates "
    "its intended message at the stated view-tier. Deterministic metrics "
    "(edge crossings, node overlap, whitespace, palette/contrast/a11y) are "
    "provided as context -- do not re-derive them, judge what they miss."
)

# The provenance field the D8 copy-paste driver forces (contracts/copy_paste.py
# reads MODE_FIELD explicitly). Declared here so the driver's behaviour is a
# stated contract, not a coincidental match with a hardcoded fallback literal.
MODE_FIELD = "reviewer_mode"

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
    FieldSpec("reviewer_mode", str, required=True,
              allowed_values=("harness", "copy-paste", "api", "deterministic"),
              description="Which mode produced this output -- provenance, not a quality signal. "
                          "'deterministic' = the D16 gate accepted the metrics-only verdict, no LLM. "
                          "'api' = the D17 direct-API channel ran the escalation."),
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
    """Validate a vision-review result -- from ANY mode -- against the fixed output schema."""
    errors = validate(obj, OUTPUT_SCHEMA)
    return len(errors) == 0, errors


# --------------------------------------------------------- D16 fuzzy-gate --

def assemble_metrics(svg_path: Path | str, tier: str) -> dict:
    """Run the deterministic layer (svg_metrics.check_thresholds +
    visual_quality_check) on one SVG and return the CANONICAL metrics dict the
    gate reads and the LLM prompt receives as context. The single defined
    source, so `confidence()` never has to guess at a free-form operator dict."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import visual_quality  # pure text/regex, no optional deps

    path = Path(svg_path)
    # svg_metrics needs the optional svgpathtools/svgelements; when absent it
    # sys.exit(3)s. The gate must DEGRADE, not crash: a missing geometry signal
    # simply leaves the verdict to visual_quality (which governs on its own).
    # (Exception, SystemExit) covers both a bad SVG and the missing-dependency
    # sys.exit -- SystemExit is not an Exception subclass.
    try:
        import svg_metrics
        m = svg_metrics.parse_svg(path)
        severity, messages = svg_metrics.check_thresholds(m, tier)
        svg_block = {"severity": severity, "messages": messages}
    except (Exception, SystemExit) as e:
        svg_block = {"severity": None, "messages": [f"svg_metrics unavailable: {e}"]}
    vq = visual_quality.visual_quality_check(path)
    return {"svg_metrics": svg_block, "visual_quality": vq}


def _governing_verdict(deterministic_metrics: dict) -> str | None:
    """The WORST of the two deterministic signals: BLOCK > WARN > OK. None when
    neither signal is present (metrics absent, or a non-SVG ERROR/SKIP) -- in
    which case the deterministic layer has nothing to stand on and must defer."""
    ranks = []
    sev = (deterministic_metrics.get("svg_metrics") or {}).get("severity")
    if isinstance(sev, int):
        ranks.append(sev)  # 0 pass / 1 WARN / 2 BLOCK
    vq_status = (deterministic_metrics.get("visual_quality") or {}).get("status")
    if vq_status in ("OK", "WARN", "BLOCK"):
        ranks.append({"OK": 0, "WARN": 1, "BLOCK": 2}[vq_status])
    if not ranks:
        return None
    return {0: "OK", 1: "WARN", 2: "BLOCK"}[max(ranks)]


# Confidence is U-shaped in the deterministic verdict, which is the
# tokenomics-right operating point: a CONFIDENT pass (clean geometry/a11y) and a
# CONFIDENT fail (hard BLOCK) both stand on the metrics alone; the vision LLM is
# spent only on the UNCERTAIN middle (WARN) and on missing signal, where the eye
# adds the most decision value. BLOCK sits ABOVE OK so a strict operator can
# raise the threshold to escalate clean diagrams for composition coverage while
# a hard-failing diagram (which will be regenerated) never wastes an LLM call.
_CONFIDENCE = {"BLOCK": 1.0, "OK": 0.85, "WARN": 0.4}


def confidence(deterministic_metrics: dict):
    """Confidence that the metrics-only verdict is sufficient -- the composed
    [0,1] score plus its NAMED sub-signals (G3): the governing verdict and the
    two source signals it came from. None verdict -> 0.0 (must escalate: nothing
    to stand on). Returns a confidence_gate.Confidence."""
    from contracts.confidence_gate import Confidence

    verdict = _governing_verdict(deterministic_metrics)
    signals = {
        "verdict": verdict,
        "svg_severity": (deterministic_metrics.get("svg_metrics") or {}).get("severity"),
        "vq_status": (deterministic_metrics.get("visual_quality") or {}).get("status"),
    }
    if verdict is None:
        return Confidence(0.0, signals, reason="no deterministic signal (escalate)")
    return Confidence(_CONFIDENCE[verdict], signals, reason=f"governing verdict {verdict}")


def gate(input_obj: dict, threshold: float = DEFAULT_THRESHOLD) -> tuple[str, float]:
    """The D16 escalation gate: 'accept' the metrics-only verdict at/above the
    threshold (zero LLM tokens), else 'escalate' to the vision LLM. The
    accept/escalate comparison is the shared primitive; the score is per-step."""
    from contracts import confidence_gate

    conf = confidence(input_obj.get("deterministic_metrics", {}))
    return confidence_gate.decide(conf.score, threshold), conf


def deterministic_entry(input_obj: dict) -> dict:
    """Synthesize an OUTPUT_SCHEMA-shaped review from the metrics alone, for the
    accept path (no LLM). Called only when gate() accepted, i.e. a CONFIDENT OK
    or BLOCK verdict; reviewer_mode='deterministic'."""
    m = input_obj.get("deterministic_metrics", {})
    tier = input_obj.get("tier", "")
    verdict = _governing_verdict(m)
    svg = m.get("svg_metrics") or {}
    vq = m.get("visual_quality") or {}

    if verdict == "BLOCK":
        msgs = [x for x in svg.get("messages", []) if x.startswith("BLOCK")]
        msgs += vq.get("hard_violations", [])
        findings = [{"criterion": "deterministic-metric", "severity": "block", "comment": x}
                    for x in msgs] or [
            {"criterion": "deterministic-metric", "severity": "block",
             "comment": "hard threshold breach in the deterministic layer"}]
        summary = (
            f"Hard geometry/palette/contrast/a11y violations at tier '{tier}'. The "
            "deterministic layer already identifies the defects; no subjective judgment is "
            "spent on a diagram that will be reworked and regenerated.")
        status = "BLOCK"
    else:  # clean OK (WARN/None escalate and never reach here)
        findings = [{"criterion": "deterministic-metrics", "severity": "info",
                     "comment": f"geometry, palette, contrast and a11y within tier '{tier}' thresholds"}]
        summary = (
            f"All deterministic metrics within tier '{tier}' thresholds; no defect the numbers can "
            "see. Subjective composition (hierarchy/legend/flow) was NOT reviewed -- deterministic "
            "capture. Lower the threshold to escalate clean diagrams for compositional coverage.")
        status = "OK"
    return {"status": status, "findings": findings, "summary": summary,
            "reviewer_mode": "deterministic"}
