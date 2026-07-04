"""
Tests for the D16 fuzzy-gate retrofit of vision-review (Track G, item G1):
run the deterministic svg_metrics/visual_quality verdict FIRST, and escalate the
vision LLM only past a confidence threshold.

Covers: the U-shaped confidence (a confident PASS and a confident BLOCK both
stand on the metrics alone; the uncertain WARN band and missing-signal escalate);
the gate's accept/escalate boundary and the BLOCK-above-OK tunability; the
worst-of-two governing verdict; the deterministic entry for OK and BLOCK
(schema-valid, reviewer_mode='deterministic'); the canonical metrics assembler
run on real SVGs; and the render.py CLI end to end for the accept path (clean and
block SVGs -> deterministic entry, ZERO tokens, the copy-paste flow never runs),
the escalate path (WARN metrics -> gate escalates -> the copy-paste prompt is
composed and a pasted reply is validated with reviewer_mode forced), and
--force-review bypassing the gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lint"))

import vision_review_contract as vr  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"
TIER = "operator-handoff"

_CLEAN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" width="800" height="600" '
    'role="img" aria-labelledby="t d">\n'
    '  <title id="t">Clean two-node diagram</title>\n'
    '  <desc id="d">Two well-spaced nodes with labels</desc>\n'
    '  <rect x="80" y="80" width="160" height="60" fill="#ffffff"/>\n'
    '  <rect x="520" y="440" width="160" height="60" fill="#ffffff"/>\n'
    '  <text x="95" y="115" fill="#000000">Gateway</text>\n'
    '  <text x="535" y="475" fill="#000000">Ledger</text>\n'
    "</svg>\n"
)
# missing role + aria-labelledby -> GR-8 accessibility BLOCK
_BLOCK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" width="800" height="600">\n'
    '  <rect x="80" y="80" width="140" height="50" fill="#000000"/>\n'
    "</svg>\n"
)


def _metrics(sev, vq):
    return {"svg_metrics": {"severity": sev, "messages": []}, "visual_quality": {"status": vq}}


def _input(sev, vq):
    return {"deterministic_metrics": _metrics(sev, vq), "tier": TIER}


# ------------------------------------------------------ confidence + gate --

@pytest.mark.parametrize("sev,vq,expected", [
    (0, "OK", 0.85),     # confident pass
    (2, "OK", 1.0),      # confident fail (svg BLOCK)
    (0, "BLOCK", 1.0),   # confident fail (vq BLOCK)
    (1, "OK", 0.4),      # svg WARN -> uncertain
    (0, "WARN", 0.4),    # vq WARN -> uncertain
    (None, "SKIP", 0.0),  # no signal
    (None, "ERROR", 0.0),
])
def test_confidence_u_shape(sev, vq, expected):
    assert vr.confidence(_metrics(sev, vq)) == pytest.approx(expected)


def test_worst_of_two_governs():
    # svg clean but vq BLOCK -> BLOCK; svg WARN but vq OK -> WARN
    assert vr._governing_verdict(_metrics(0, "BLOCK")) == "BLOCK"
    assert vr._governing_verdict(_metrics(1, "OK")) == "WARN"
    assert vr._governing_verdict(_metrics(0, "OK")) == "OK"
    assert vr._governing_verdict(_metrics(None, "SKIP")) is None


def test_gate_default_threshold():
    assert vr.gate(_input(0, "OK"))[0] == "accept"     # 0.85
    assert vr.gate(_input(2, "OK"))[0] == "accept"     # 1.0
    assert vr.gate(_input(1, "OK"))[0] == "escalate"   # 0.4
    assert vr.gate(_input(None, "SKIP"))[0] == "escalate"  # 0.0


def test_block_sits_above_ok_for_strict_operator():
    """A strict threshold escalates a CLEAN diagram for compositional coverage
    while a hard-failing one (regenerated anyway) never wastes an LLM call."""
    assert vr.gate(_input(0, "OK"), threshold=0.9)[0] == "escalate"  # 0.85 < 0.9
    assert vr.gate(_input(2, "OK"), threshold=0.9)[0] == "accept"    # 1.0 >= 0.9


# ------------------------------------------------- deterministic entries --

def test_deterministic_entry_ok_is_schema_valid():
    entry = vr.deterministic_entry(_input(0, "OK"))
    ok, errors = vr.validate_output(entry)
    assert ok, errors
    assert entry["status"] == "OK"
    assert entry["reviewer_mode"] == "deterministic"


def test_deterministic_entry_block_lists_violations():
    m = {"svg_metrics": {"severity": 2, "messages": ["BLOCK edge_crossings=9 > tier block=4"]},
         "visual_quality": {"status": "BLOCK", "hard_violations": ["GR-8 accessibility: 2 issues"]}}
    entry = vr.deterministic_entry({"deterministic_metrics": m, "tier": TIER})
    ok, errors = vr.validate_output(entry)
    assert ok, errors
    assert entry["status"] == "BLOCK"
    comments = " ".join(f["comment"] for f in entry["findings"])
    assert "edge_crossings" in comments and "accessibility" in comments
    assert all(f["severity"] == "block" for f in entry["findings"])


def test_reviewer_mode_deterministic_is_valid():
    ok, _ = vr.validate_output({"status": "OK", "findings": [], "summary": "x",
                                "reviewer_mode": "deterministic"})
    assert ok


# ------------------------------------------------------ assemble_metrics --

def test_assemble_metrics_canonical_shape_clean(tmp_path):
    svg = tmp_path / "clean.svg"
    svg.write_text(_CLEAN_SVG, encoding="utf-8")
    m = vr.assemble_metrics(svg, TIER)
    assert set(m) == {"svg_metrics", "visual_quality"}
    assert m["svg_metrics"]["severity"] == 0
    assert m["visual_quality"]["status"] == "OK"
    assert vr._governing_verdict(m) == "OK"


def test_assemble_metrics_block_on_missing_a11y(tmp_path):
    svg = tmp_path / "block.svg"
    svg.write_text(_BLOCK_SVG, encoding="utf-8")
    m = vr.assemble_metrics(svg, TIER)
    assert m["visual_quality"]["status"] == "BLOCK"
    assert vr._governing_verdict(m) == "BLOCK"


# --------------------------------------------------------------- CLI --

def _run(args, stdin=""):
    return subprocess.run(
        [sys.executable, str(RENDER_PY), "copy-paste", "vision-review", *args],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), input=stdin)


def _last_json(text):
    """The escalate path prints the paste-prompt AND the final result to stdout;
    the result is the last top-level pretty-printed JSON object. Parse that."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.rstrip() == "{"]
    assert starts, f"no top-level JSON object in stdout:\n{text[:400]}"
    return json.loads("\n".join(lines[starts[-1]:]))


def test_cli_accept_path_spends_zero_tokens(tmp_path):
    svg = tmp_path / "clean.svg"
    svg.write_text(_CLEAN_SVG, encoding="utf-8")
    r = _run(["--tier", TIER, "--image", str(svg)])
    assert r.returncode == 0, r.stderr
    entry = json.loads(r.stdout)
    assert entry["status"] == "OK"
    assert entry["reviewer_mode"] == "deterministic"
    assert "-> accept" in r.stderr
    # the copy-paste flow must NOT have run: no paste prompt was ever emitted
    assert "Paste the LLM" not in r.stdout and "Paste the LLM" not in r.stderr


def test_cli_block_accept_path(tmp_path):
    svg = tmp_path / "block.svg"
    svg.write_text(_BLOCK_SVG, encoding="utf-8")
    r = _run(["--tier", TIER, "--image", str(svg)])
    assert r.returncode == 0, r.stderr
    entry = json.loads(r.stdout)
    assert entry["status"] == "BLOCK"
    assert entry["reviewer_mode"] == "deterministic"


def test_cli_escalate_path_runs_the_llm(tmp_path):
    # WARN metrics -> gate escalates -> copy-paste prompt composed; a valid pasted
    # reply is validated and its provenance forced to copy-paste
    warn_metrics = json.dumps(_metrics(1, "OK"))
    pasted = json.dumps({
        "status": "WARN",
        "findings": [{"criterion": "visual-hierarchy", "severity": "warn",
                      "comment": "the title competes with the legend for first fixation"}],
        "summary": "Borderline hierarchy; legend could be demoted.",
        "reviewer_mode": "harness",  # deliberately wrong; the driver must overwrite
    })
    r = _run(["--tier", TIER, "--image", "diagram.png", "--metrics-json", warn_metrics],
             stdin=pasted + "\nEND\n")
    assert r.returncode == 0, r.stderr
    assert "-> escalate" in r.stderr
    result = _last_json(r.stdout)
    assert result["reviewer_mode"] == "copy-paste"  # forced by the driver
    assert result["status"] == "WARN"


def test_cli_force_review_bypasses_gate(tmp_path):
    svg = tmp_path / "clean.svg"
    svg.write_text(_CLEAN_SVG, encoding="utf-8")
    pasted = json.dumps({"status": "OK", "findings": [], "summary": "looks good",
                         "reviewer_mode": "harness"})
    r = _run(["--tier", TIER, "--image", str(svg), "--force-review"], stdin=pasted + "\nEND\n")
    assert r.returncode == 0, r.stderr
    # gate was bypassed: no accept line, the LLM path ran
    assert "-> accept" not in r.stderr
    result = _last_json(r.stdout)
    assert result["reviewer_mode"] == "copy-paste"
