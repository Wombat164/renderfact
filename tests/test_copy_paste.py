"""
Tests for contracts/copy_paste.py -- D8 copy-paste fallback (chunk 3.4),
implementing docs/2026-07-03-d8-copy-paste-design-spike.md.

Covers: prompt composition includes the real vision-review schema + input data
+ attach note, delivery writes a scratch file, the stdin-sentinel reader stops
at the right line, the JSON/YAML/fenced-block parser handles all three shapes
and rejects non-object results, and the full run_copy_paste_step loop -- happy
path, a retry that recovers, and exhausting the retry budget -- against the
REAL vision-review contract (not a stub), matching the design doc's own
worked example.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lint"))

from contracts import copy_paste  # noqa: E402
import vision_review_contract as vrc  # noqa: E402


SAMPLE_INPUT = vrc.assemble_input(
    "renders/fog-edge-tenancy-hero.png",
    "operator-handoff",
    {"edge_crossings": 3, "node_overlap_pairs": 0, "whitespace_pct": 41.2},
)

VALID_RESULT = {
    "status": "WARN",
    "findings": [
        {"criterion": "legend-clarity", "severity": "warn", "comment": "Legend overlaps a node label."},
    ],
    "summary": "Mostly clear; legend placement needs adjustment.",
    "reviewer_mode": "copy-paste",
}


def test_compose_prompt_includes_instructions_input_and_attach_note():
    prompt = copy_paste.compose_prompt("vision-review", vrc, SAMPLE_INPUT)
    assert "## vision-review" in prompt
    assert '"copy-paste"' in prompt  # mode="copy-paste" was passed through
    assert json.dumps(SAMPLE_INPUT, indent=2) in prompt
    assert "ATTACH the image at: renders/fog-edge-tenancy-hero.png" in prompt
    assert "Respond with ONLY a single JSON object" in prompt


def test_compose_prompt_omits_attach_note_when_no_image_path():
    obj = {"task_intent": "x", "tier": "operator-handoff"}  # no rendered_image_path key
    prompt = copy_paste.compose_prompt("vision-review", vrc, obj)
    assert "ATTACH the image" not in prompt


def test_try_copy_to_clipboard_returns_false_when_no_tool_available(monkeypatch):
    import subprocess

    monkeypatch.setattr(sys, "platform", "linux")

    def fail(*a, **kw):
        raise FileNotFoundError("no such tool")

    monkeypatch.setattr(subprocess, "run", fail)
    assert copy_paste._try_copy_to_clipboard("hello") is False


def test_try_copy_to_clipboard_falls_back_to_second_candidate(monkeypatch):
    import subprocess

    monkeypatch.setattr(sys, "platform", "linux")
    calls = []

    def fake_run(cmd, input, check, timeout):
        calls.append(cmd[0])
        if cmd[0] == "xclip":
            raise FileNotFoundError("xclip not installed")
        return None  # xsel "succeeds"

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert copy_paste._try_copy_to_clipboard("hello") is True
    assert calls == ["xclip", "xsel"]


def test_deliver_prompt_writes_scratch_file_and_prints(tmp_path, monkeypatch):
    monkeypatch.setattr(copy_paste, "_try_copy_to_clipboard", lambda text: False)
    buf = io.StringIO()
    path = copy_paste.deliver_prompt("PROMPT TEXT", tmp_path, out=buf)
    assert path == tmp_path / copy_paste.SCRATCH_FILENAME
    assert path.read_text(encoding="utf-8") == "PROMPT TEXT"
    assert "PROMPT TEXT" in buf.getvalue()
    assert "copied to your clipboard" not in buf.getvalue()


def test_deliver_prompt_reports_clipboard_copy_when_it_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(copy_paste, "_try_copy_to_clipboard", lambda text: True)
    buf = io.StringIO()
    copy_paste.deliver_prompt("PROMPT TEXT", tmp_path, out=buf)
    assert "copied to your clipboard" in buf.getvalue()


def test_read_pasted_response_reads_until_sentinel():
    lines = iter(["line1\n", "line2\n", "END\n", "ignored-after-sentinel\n"])
    result = copy_paste.read_pasted_response(lines_source=lines, out=io.StringIO())
    assert result == "line1\nline2"


def test_parse_llm_response_raw_json():
    assert copy_paste.parse_llm_response(json.dumps(VALID_RESULT)) == VALID_RESULT


def test_parse_llm_response_fenced_json():
    fenced = "```json\n" + json.dumps(VALID_RESULT) + "\n```"
    assert copy_paste.parse_llm_response(fenced) == VALID_RESULT


def test_parse_llm_response_yaml():
    yaml_text = "status: OK\nfindings: []\nsummary: Clear.\nreviewer_mode: copy-paste\n"
    result = copy_paste.parse_llm_response(yaml_text)
    assert result["status"] == "OK"
    assert result["findings"] == []


def test_parse_llm_response_rejects_non_object_json():
    with pytest.raises(ValueError, match="could not parse"):
        copy_paste.parse_llm_response("[1, 2, 3]")


def test_parse_llm_response_raises_on_garbage():
    with pytest.raises(ValueError, match="could not parse"):
        copy_paste.parse_llm_response("this is not JSON or YAML: {{{")


def test_run_copy_paste_step_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr(copy_paste, "_try_copy_to_clipboard", lambda text: False)
    pasted = iter([json.dumps(VALID_RESULT), "END"])
    out = io.StringIO()

    result = copy_paste.run_copy_paste_step(
        "vision-review", vrc, SAMPLE_INPUT, scratch_dir=tmp_path, lines_source=pasted, out=out
    )
    assert result["status"] == "WARN"
    assert result["reviewer_mode"] == "copy-paste"
    assert (tmp_path / copy_paste.SCRATCH_FILENAME).exists()


def test_run_copy_paste_step_forces_reviewer_mode_even_if_pasted_wrong(tmp_path):
    bad_provenance = dict(VALID_RESULT)
    bad_provenance["reviewer_mode"] = "harness"  # a confused human/LLM pasted the wrong mode
    pasted = iter([json.dumps(bad_provenance), "END"])

    result = copy_paste.run_copy_paste_step(
        "vision-review", vrc, SAMPLE_INPUT, scratch_dir=tmp_path, lines_source=pasted, out=io.StringIO()
    )
    assert result["reviewer_mode"] == "copy-paste"


def test_run_copy_paste_step_retries_then_succeeds(tmp_path):
    invalid = {"status": "OK"}  # missing required fields
    # One continuous stream: first attempt's bad paste + END, then a good paste + END.
    pasted = iter([json.dumps(invalid), "END", json.dumps(VALID_RESULT), "END"])
    out = io.StringIO()

    result = copy_paste.run_copy_paste_step(
        "vision-review", vrc, SAMPLE_INPUT, scratch_dir=tmp_path, lines_source=pasted, out=out
    )
    assert result["status"] == "WARN"
    assert "BLOCKED (attempt 1/3)" in out.getvalue()


def test_run_copy_paste_step_recovers_from_unparseable_paste(tmp_path):
    pasted = iter(["not json or yaml: {{{", "END", json.dumps(VALID_RESULT), "END"])
    result = copy_paste.run_copy_paste_step(
        "vision-review", vrc, SAMPLE_INPUT, scratch_dir=tmp_path, lines_source=pasted, out=io.StringIO()
    )
    assert result["status"] == "WARN"


def test_run_copy_paste_step_exhausts_retries_raises(tmp_path):
    invalid = {"status": "OK"}
    pasted = iter([json.dumps(invalid), "END"] * 3)

    with pytest.raises(copy_paste.CopyPasteValidationError, match="still failed validation after 3 attempts"):
        copy_paste.run_copy_paste_step(
            "vision-review",
            vrc,
            SAMPLE_INPUT,
            scratch_dir=tmp_path,
            lines_source=pasted,
            max_retries=3,
            out=io.StringIO(),
        )
