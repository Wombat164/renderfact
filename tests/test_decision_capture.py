"""
Tests for roundtrip/decision_capture.py (C8.3: the editable-diagram round-trip
decision-capture step, and renderfact's worked example of the D16 fuzzy-gate
doctrine -- deterministic first, LLM handoff only past a confidence threshold).

Covers: the confidence heuristic across change kinds / volume / verdict; the
gate's accept/escalate boundary; the deterministic template (empty, relabel,
add) producing schema-valid entries; input assembly from a `reingest --json`
result; markdown rendering and the append sink; the D8 contract (the generic
copy_paste driver drives decision-capture from an injected paste, forcing
capture_mode); the CLI end to end for both the accept (zero-token) path and the
below-threshold needs_review path; and init-ai exposing the step to a harness.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "roundtrip"))

import decision_capture as dc  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"


def _input(kinds, verdict="FAST_FORWARD"):
    reingest = {"verdict": verdict,
                "semantic": [{"kind": k, "id": f"n{i}", "old": "a", "new": "b"}
                             for i, k in enumerate(kinds)]}
    return dc.assemble_input(reingest, "s.yaml", "Payment platform")


# -------------------------------------------------------------- confidence --

@pytest.mark.parametrize("kinds,verdict,expected", [
    ([], "FAST_FORWARD", 1.0),                              # cosmetic only
    (["relabel-node"], "FAST_FORWARD", 1.0),                # pure descriptive
    (["relabel-node"], "DIVERGED", 0.7),                    # descriptive, source moved
    (["add-node"], "FAST_FORWARD", 0.0),                    # pure intent
    (["relabel-node"] * 3 + ["add-node"], "FAST_FORWARD", 0.5625),  # mixed
    (["relabel-node"] * 6, "FAST_FORWARD", 0.5),            # high volume
])
def test_confidence_values(kinds, verdict, expected):
    assert dc.confidence(_input(kinds, verdict)) == pytest.approx(expected)


def test_gate_accepts_at_and_above_threshold():
    obj = _input(["relabel-node"], "DIVERGED")  # 0.7
    assert dc.gate(obj, threshold=0.7) == ("accept", 0.7)
    assert dc.gate(obj, threshold=0.71)[0] == "escalate"


def test_gate_default_threshold_splits_descriptive_from_intent():
    assert dc.gate(_input(["relabel-node"]))[0] == "accept"
    assert dc.gate(_input(["add-node"]))[0] == "escalate"


# --------------------------------------------------- deterministic entries --

def test_deterministic_empty_is_cosmetic_only_and_valid():
    entry = dc.deterministic_entry(_input([]))
    ok, errors = dc.validate_output(entry)
    assert ok, errors
    assert entry["changes"] == []
    assert "layout/style" in entry["title"] or "layout/style" in entry["summary"]
    assert entry["capture_mode"] == "deterministic"


def test_deterministic_templates_each_kind_and_validates():
    reingest = {"verdict": "FAST_FORWARD", "semantic": [
        {"kind": "relabel-node", "id": "gateway", "old": "API Gateway", "new": "Public API Gateway"},
        {"kind": "add-node", "id": "fraud", "new": "Fraud Check"},
        {"kind": "remove-edge", "id": "rel:auth->ledger", "old": "auth->ledger ''"},
        {"kind": "rewire-edge", "id": "e1", "old": "a->b", "new": "a->c"},
    ]}
    obj = dc.assemble_input(reingest, "pay.yaml", "Payment platform")
    entry = dc.deterministic_entry(obj)
    ok, errors = dc.validate_output(entry)
    assert ok, errors
    joined = " ".join(entry["changes"])
    assert "Renamed node 'gateway'" in joined
    assert "Added node 'fraud'" in joined
    assert "Removed edge" in joined
    assert "Rewired edge 'e1' from a->b to a->c" in joined
    assert len(entry["changes"]) == 4


def test_diverged_summary_flags_reconciliation():
    entry = dc.deterministic_entry(_input(["add-node"], "DIVERGED"))
    assert "DIVERGED" in entry["summary"]


# --------------------------------------------------------- assemble_input --

def test_assemble_input_shape_and_schema():
    obj = _input(["relabel-node", "add-node"])
    assert obj["task_intent"] == dc.TASK_INTENT
    assert obj["source_name"] == "s.yaml"
    assert obj["diagram_title"] == "Payment platform"
    assert [c["kind"] for c in obj["semantic_changes"]] == ["relabel-node", "add-node"]


# ------------------------------------------------------- markdown + sink --

def test_render_markdown_is_deterministic_without_timestamp():
    obj = _input(["relabel-node"])
    entry = dc.deterministic_entry(obj)
    md = dc.render_markdown(entry, obj, source_version="deadbeef")
    assert "## " in md
    assert "- Source: s.yaml" in md
    assert "- Source version: deadbeef" in md
    assert "Captured at:" not in md  # no rendered_at -> reproducible
    # needs_review marker appears only when asked
    assert "NEEDS REVIEW" not in md
    md2 = dc.render_markdown(entry, obj, needs_review=True)
    assert "NEEDS REVIEW" in md2


def test_append_entry_creates_then_appends(tmp_path):
    log = tmp_path / "d.decisions.md"
    dc.append_entry(log, "## First\n\nbody\n")
    dc.append_entry(log, "## Second\n\nbody\n")
    text = log.read_text(encoding="utf-8")
    assert text.startswith("# Diagram decision log")
    assert text.index("## First") < text.index("## Second")
    assert "## First\n\n## Second" not in text  # a blank line separates entries


# ------------------------------------------------------------- D8 contract --

def test_copy_paste_driver_drives_decision_capture():
    """The generic D8 driver must run decision-capture from a human paste and
    force capture_mode -- proving it is a valid, mode-uniform step contract."""
    from contracts import copy_paste

    obj = _input(["add-node"])
    pasted = json.dumps({
        "title": "Add fraud-check service",
        "summary": "Compliance required an explicit fraud gate before the ledger.",
        "changes": ["Added node 'n0' (Fraud Check)."],
        "capture_mode": "harness",  # deliberately wrong: the driver must overwrite it
    })
    lines = iter(pasted.splitlines() + ["END"])
    result = copy_paste.run_copy_paste_step(
        "decision-capture", dc, obj, lines_source=lines, out=open(__import__("os").devnull, "w"))
    assert result["capture_mode"] == "copy-paste"  # forced, not trusted
    assert result["title"] == "Add fraud-check service"
    ok, errors = dc.validate_output(result)
    assert ok, errors


# --------------------------------------------------------------------- CLI --

def _graph(tmp_path):
    p = tmp_path / "g.yaml"
    p.write_text(
        "title: Payment platform\n"
        "concepts:\n  - {id: gateway, label: API Gateway}\n  - {id: auth, label: Auth Service}\n"
        "relations:\n  - {from: gateway, to: auth}\n",
        encoding="utf-8")
    return p


def test_cli_accept_path_zero_escalation(tmp_path):
    graph = _graph(tmp_path)
    reingest = tmp_path / "r.json"
    reingest.write_text(json.dumps({"verdict": "FAST_FORWARD", "semantic": [
        {"kind": "relabel-node", "id": "gateway", "old": "API Gateway", "new": "Edge Gateway"}]}),
        encoding="utf-8")
    log = tmp_path / "out.decisions.md"
    r = subprocess.run(
        [sys.executable, str(RENDER_PY), "decision-capture", "--source", str(graph),
         "--reingest", str(reingest), "--decision-log", str(log), "--json"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["decision"] == "accept"
    assert payload["confidence"] == 1.0
    assert payload["needs_review"] is False
    assert payload["entry"]["capture_mode"] == "deterministic"
    assert log.exists() and "Edge Gateway" in log.read_text(encoding="utf-8")


def test_cli_below_threshold_writes_needs_review(tmp_path):
    graph = _graph(tmp_path)
    reingest = tmp_path / "r.json"
    reingest.write_text(json.dumps({"verdict": "FAST_FORWARD", "semantic": [
        {"kind": "add-node", "id": "fraud", "new": "Fraud Check"}]}), encoding="utf-8")
    log = tmp_path / "out.decisions.md"
    r = subprocess.run(
        [sys.executable, str(RENDER_PY), "decision-capture", "--source", str(graph),
         "--reingest", str(reingest), "--decision-log", str(log), "--json"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["decision"] == "escalate"
    assert payload["needs_review"] is True
    assert "NEEDS REVIEW" in log.read_text(encoding="utf-8")


def test_cli_dry_run_does_not_write(tmp_path):
    graph = _graph(tmp_path)
    reingest = tmp_path / "r.json"
    reingest.write_text(json.dumps({"verdict": "FAST_FORWARD", "semantic": []}), encoding="utf-8")
    log = tmp_path / "out.decisions.md"
    r = subprocess.run(
        [sys.executable, str(RENDER_PY), "decision-capture", "--source", str(graph),
         "--reingest", str(reingest), "--decision-log", str(log), "--dry-run"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stderr
    assert not log.exists()


# --------------------------------------------------------------- harness --

def test_init_ai_exposes_decision_capture():
    from contracts import init_ai

    names = [n for n, _ in init_ai.step_contracts()]
    assert "decision-capture" in names
    skill = init_ai.render_claude_skill()
    assert "decision-capture" in skill
    assert dc.TASK_INTENT[:40] in skill


def test_render_copy_paste_redirects_decision_capture(tmp_path):
    """The vision-shaped `render copy-paste` CLI must not mis-drive decision-capture;
    it points the user at the step's own gated command."""
    r = subprocess.run(
        [sys.executable, str(RENDER_PY), "copy-paste", "decision-capture"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), input="")
    assert r.returncode == 2
    assert "decision-capture --escalate copy-paste" in r.stderr
