"""
Tests for roundtrip/contextualize.py (Track D 4.5 / Track G item G6): the
document round-trip contextualize step. Mirrors test_decision_capture.py's
scenario set, over reingest's `manual` diff instead of a diagram's semantic diff.

Covers: the reingest-tuple classifier; the confidence heuristic (reword-only ->
accept, added/deleted/heading -> escalate, scaled by volume + DIVERGED); the
deterministic entry per kind; assemble_input from a reingest --json shape; the
CLI accept / needs-review / dry-run paths; and the harness integration (init-ai
exposure, the render copy-paste redirect, MODE_FIELD).
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

import contextualize as ctx  # noqa: E402
from reingest import ADDED_MARKER, DELETED_MARKER, WHY_HEADING, WHY_INLINE_MARKUP  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"


def _input(manual, verdict="FAST_FORWARD"):
    return ctx.assemble_input({"verdict": verdict, "manual": manual}, "doc.md", "My Doc")


# --------------------------------------------------------------- classify --

@pytest.mark.parametrize("item,expected", [
    (["old", "new", WHY_INLINE_MARKUP], "reword"),
    (["old", "new", "normalized text not unique in the source"], "reword"),
    (["#> Heading", "#> New Heading", WHY_HEADING], "heading"),
    ([ADDED_MARKER, "brand new line"], "add"),
    (["gone line", DELETED_MARKER], "delete"),
    (["short", "much longer replaced content"], "replace"),
])
def test_classify(item, expected):
    assert ctx.classify(item) == expected


# -------------------------------------------------------------- confidence --

@pytest.mark.parametrize("manual,verdict,expected", [
    ([], "FAST_FORWARD", 1.0),                                       # nothing manual
    ([], "DIVERGED", 0.7),                                           # nothing manual but source moved
    ([["a", "b", WHY_INLINE_MARKUP]], "FAST_FORWARD", 1.0),          # pure reword
    ([["a", "b", WHY_INLINE_MARKUP]], "DIVERGED", 0.7),              # reword, source moved
    ([[ADDED_MARKER, "x"]], "FAST_FORWARD", 0.0),                    # pure add (intent)
    ([["a", "b", WHY_INLINE_MARKUP]] * 3 + [[ADDED_MARKER, "x"]], "FAST_FORWARD", 0.5625),  # mixed
    ([["a", "b", WHY_INLINE_MARKUP]] * 6, "FAST_FORWARD", 0.5),      # high volume
])
def test_confidence_values(manual, verdict, expected):
    conf = ctx.confidence(_input(manual, verdict))
    assert conf.score == pytest.approx(expected)
    assert set(conf.signals) == {"change_count", "intent_ratio", "volume_factor", "verdict_factor"}


def test_heading_edit_is_intent_bearing():
    assert ctx.confidence(_input([["#> H", "#> H2", WHY_HEADING]])).score == pytest.approx(0.0)


def test_gate_splits_reword_from_content():
    assert ctx.gate(_input([["a", "b", WHY_INLINE_MARKUP]]))[0] == "accept"
    assert ctx.gate(_input([[ADDED_MARKER, "new"]]))[0] == "escalate"


# ------------------------------------------------ deterministic entries --

def test_empty_manual_valid_and_cosmetic():
    entry = ctx.deterministic_entry(_input([]))
    ok, errors = ctx.validate_output(entry)
    assert ok, errors
    assert entry["changes"] == [] and "no manual-review" in entry["title"]


def test_empty_manual_diverged_flags_reconciliation():
    entry = ctx.deterministic_entry(_input([], "DIVERGED"))
    assert "DIVERGED" in entry["summary"]


def test_deterministic_templates_each_kind():
    manual = [["old", "new", WHY_INLINE_MARKUP], [ADDED_MARKER, "added para"],
              ["gone", DELETED_MARKER], ["#> A", "#> B", WHY_HEADING], ["s", "longer replaced"]]
    entry = ctx.deterministic_entry(_input(manual))
    ok, errors = ctx.validate_output(entry)
    assert ok, errors
    joined = " ".join(entry["changes"])
    assert "Reworded a line" in joined and "Added a line" in joined and "Deleted a line" in joined
    assert "Edited a heading" in joined and "Replaced content" in joined


# --------------------------------------------------------- assemble_input --

def test_assemble_input_shape():
    obj = _input([[ADDED_MARKER, "x"], ["a", "b", WHY_INLINE_MARKUP]])
    assert obj["task_intent"] == ctx.TASK_INTENT
    assert obj["source_name"] == "doc.md" and obj["doc_title"] == "My Doc"
    assert [c["kind"] for c in obj["manual_changes"]] == ["add", "reword"]
    assert obj["round"] == 1
    assert obj["prior_rounds"] == []


# ------------------------------------------------ G8: multi-round narrative --

def test_parse_prior_rounds_returns_empty_for_missing_log(tmp_path):
    assert ctx.parse_prior_rounds(tmp_path / "does-not-exist.md", "doc.md") == []


def test_parse_prior_rounds_returns_empty_when_no_matching_source(tmp_path):
    log = tmp_path / "log.md"
    entry = ctx.render_markdown(
        {"title": "Other doc: 1 edit", "summary": "Some summary.", "changes": [], "capture_mode": "deterministic"},
        {"source_name": "other.md", "verdict": "FAST_FORWARD"},
    )
    ctx.append_entry(log, entry)
    assert ctx.parse_prior_rounds(log, "doc.md") == []


def test_parse_prior_rounds_parses_matching_entries_in_order(tmp_path):
    log = tmp_path / "log.md"
    for i in range(2):
        entry = ctx.render_markdown(
            {"title": f"Doc: round {i + 1} edit", "summary": f"Summary for round {i + 1}.",
             "changes": [f"change {i + 1}"], "capture_mode": "deterministic"},
            {"source_name": "doc.md", "verdict": "FAST_FORWARD"},
        )
        ctx.append_entry(log, entry)
    prior = ctx.parse_prior_rounds(log, "doc.md")
    assert [p["round"] for p in prior] == [1, 2]
    assert prior[0]["title"] == "Doc: round 1 edit"
    assert prior[0]["summary"] == "Summary for round 1."
    assert prior[1]["title"] == "Doc: round 2 edit"


def test_assemble_input_round_increments_with_prior_rounds():
    prior = [{"round": 1, "title": "Doc: 1 edit", "summary": "First round summary."}]
    obj = ctx.assemble_input({"verdict": "FAST_FORWARD", "manual": []}, "doc.md", "My Doc", prior_rounds=prior)
    assert obj["round"] == 2
    assert obj["prior_rounds"] == prior


def test_task_intent_extended_with_prior_round_context():
    prior = [{"round": 1, "title": "Doc: 1 edit", "summary": "First round summary."}]
    obj = ctx.assemble_input({"verdict": "FAST_FORWARD", "manual": []}, "doc.md", "My Doc", prior_rounds=prior)
    assert obj["task_intent"] != ctx.TASK_INTENT
    assert ctx.TASK_INTENT in obj["task_intent"]
    assert "First round summary." in obj["task_intent"]
    assert "Doc: 1 edit" in obj["task_intent"]


def test_deterministic_entry_round_1_has_no_prefix_or_note():
    obj = _input([[ADDED_MARKER, "x"]])
    entry = ctx.deterministic_entry(obj)
    assert not entry["title"].startswith("Round")
    assert "round" not in entry["summary"].lower()


def test_deterministic_entry_round_2_is_prefixed_and_notes_prior_round():
    prior = [{"round": 1, "title": "My Doc: 1 edit", "summary": "First round summary."}]
    obj = ctx.assemble_input({"verdict": "FAST_FORWARD", "manual": [[ADDED_MARKER, "x"]]},
                             "doc.md", "My Doc", prior_rounds=prior)
    entry = ctx.deterministic_entry(obj)
    assert entry["title"].startswith("Round 2: ")
    assert "round 1" in entry["summary"].lower()
    assert "My Doc: 1 edit" in entry["summary"]


def test_deterministic_entry_round_2_no_manual_changes_still_notes_prior_round():
    prior = [{"round": 1, "title": "My Doc: 1 edit", "summary": "First round summary."}]
    obj = ctx.assemble_input({"verdict": "FAST_FORWARD", "manual": []},
                             "doc.md", "My Doc", prior_rounds=prior)
    entry = ctx.deterministic_entry(obj)
    assert entry["title"].startswith("Round 2: ")
    assert "round 1" in entry["summary"].lower()


# --------------------------------------------------------------------- CLI --

def _src(tmp_path):
    p = tmp_path / "src.md"
    p.write_text("# Doc\n\nhello\n", encoding="utf-8")
    return p


def _cli(src, reingest_path, extra=(), tmp_path=None):
    log = (tmp_path / "out.decisions.md") if tmp_path else None
    args = [sys.executable, str(RENDER_PY), "contextualize", "--source", str(src),
            "--reingest", str(reingest_path), "--json", *extra]
    if log:
        args += ["--decision-log", str(log)]
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT))
    return r, log


def test_cli_accept_path(tmp_path):
    src = _src(tmp_path)
    reingest = tmp_path / "r.json"
    reingest.write_text(json.dumps({"verdict": "FAST_FORWARD",
                                    "provenance": {"source_version": "v1"},
                                    "manual": [["a", "b", WHY_INLINE_MARKUP]]}), encoding="utf-8")
    r, log = _cli(src, reingest, tmp_path=tmp_path)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["decision"] == "accept" and d["needs_review"] is False
    assert log.exists() and "v1" in log.read_text(encoding="utf-8")


def test_cli_below_threshold_needs_review(tmp_path):
    src = _src(tmp_path)
    reingest = tmp_path / "r.json"
    reingest.write_text(json.dumps({"verdict": "FAST_FORWARD", "provenance": {},
                                    "manual": [[ADDED_MARKER, "new para"]]}), encoding="utf-8")
    r, log = _cli(src, reingest, tmp_path=tmp_path)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["decision"] == "escalate" and d["needs_review"] is True
    assert "NEEDS REVIEW" in log.read_text(encoding="utf-8")


def test_cli_dry_run_does_not_write(tmp_path):
    src = _src(tmp_path)
    reingest = tmp_path / "r.json"
    reingest.write_text(json.dumps({"verdict": "FAST_FORWARD", "provenance": {}, "manual": []}),
                        encoding="utf-8")
    r, log = _cli(src, reingest, extra=["--dry-run"], tmp_path=tmp_path)
    assert r.returncode == 0, r.stderr
    assert not log.exists()


def test_cli_stdin_reingest(tmp_path):
    src = _src(tmp_path)
    payload = json.dumps({"verdict": "DIVERGED", "provenance": {"source_version": "v2"}, "manual": []})
    r = subprocess.run(
        [sys.executable, str(RENDER_PY), "contextualize", "--source", str(src),
         "--reingest", "-", "--decision-log", str(tmp_path / "d.md"), "--json"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), input=payload)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    # empty manual + DIVERGED -> confidence 0.7 -> accept at default 0.6, with reconciliation note
    assert d["decision"] == "accept"


def test_cli_second_round_increments_and_references_first(tmp_path):
    src = _src(tmp_path)
    reingest = tmp_path / "r.json"
    reingest.write_text(json.dumps({"verdict": "FAST_FORWARD", "provenance": {},
                                    "manual": [[ADDED_MARKER, "first round content"]]}), encoding="utf-8")
    r1, log = _cli(src, reingest, tmp_path=tmp_path)
    assert r1.returncode == 0, r1.stderr
    d1 = json.loads(r1.stdout)
    assert d1["round"] == 1

    reingest.write_text(json.dumps({"verdict": "FAST_FORWARD", "provenance": {},
                                    "manual": [[ADDED_MARKER, "second round content"]]}), encoding="utf-8")
    r2, _ = _cli(src, reingest, tmp_path=tmp_path)
    assert r2.returncode == 0, r2.stderr
    d2 = json.loads(r2.stdout)
    assert d2["round"] == 2

    log_text = log.read_text(encoding="utf-8")
    assert "Round 2:" in log_text
    assert log_text.count("## ") == 2  # both rounds present, not overwritten


# --------------------------------------------------------------- harness --

def test_init_ai_exposes_contextualize():
    from contracts import init_ai

    names = [n for n, _ in init_ai.step_contracts()]
    assert "contextualize" in names
    assert ctx.TASK_INTENT[:30] in init_ai.render_claude_skill()


def test_render_copy_paste_redirects_contextualize():
    assert ctx.HAS_OWN_GATE is True
    r = subprocess.run(
        [sys.executable, str(RENDER_PY), "copy-paste", "contextualize"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), input="")
    assert r.returncode == 2
    assert "contextualize --escalate copy-paste" in r.stderr
