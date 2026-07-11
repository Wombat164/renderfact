"""
Integration tests for the two hook additions to container/render-doc.sh (issue
#71, D18):

1. QC_SCRIPT blocking mode: advisory by default (a failing QC_SCRIPT does not
   stop the render); QC_BLOCKING=1 or --qc-blocking make a non-zero exit stop
   the render instead.
2. The new POSTRENDER_GATE_SCRIPT hook: fires after render (once the docx is
   finished) with the finished <docx> path as its argument, before the
   completion summary; blocking by default; POSTRENDER_GATE_ADVISORY=1 opts
   back into advisory-only.

Runs the REAL pipeline (bash + pandoc), same pattern as
test_render_doc_provenance.py, so it skips gracefully on hosts without those
engines.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RENDER_PY = REPO_ROOT / "render.py"

SOURCE = """---
title: Gate Hook Wiring Check
version: v1
---

# Overview

Plain paragraph, nothing sensitive.
"""

# A tiny script that always fails: stands in for either QC_SCRIPT or
# POSTRENDER_GATE_SCRIPT depending on which env var points at it.
ALWAYS_FAIL_SCRIPT = """
import sys
print("FAKE-GATE: simulated finding")
sys.exit(1)
"""

# Writes the argument it was called with to a marker file, then exits 0, so a
# test can assert exactly what path the hook fired with and that it ran at
# the right point in the pipeline (once a finished .docx exists).
RECORD_ARG_SCRIPT = """
import sys
from pathlib import Path
marker = Path(sys.argv[0]).parent / "called-with.txt"
marker.write_text(sys.argv[1], encoding="utf-8")
target = Path(sys.argv[1])
sys.exit(0 if target.is_file() and target.suffix == ".docx" else 3)
"""


def _render(tmp_path: Path, out_dir: str, *extra: str, env_extra: dict | None = None):
    src = tmp_path / "wiring.md"
    if not src.exists():
        src.write_text(SOURCE, encoding="utf-8")
    env = {**os.environ, "OUTPUT_DIR": str(tmp_path / out_dir), **(env_extra or {})}
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "docx", str(src), *extra],
        capture_output=True, text=True, timeout=180, env=env, cwd=tmp_path,
    )
    combined = result.stdout + result.stderr
    if result.returncode == 3 and ("pandoc not found" in combined or "bash not found" in combined):
        pytest.skip("render engines not installed on this host: " + combined.strip()[:120])
    return src, result.returncode, combined


def _docx_files(tmp_path: Path, out_dir: str) -> list[Path]:
    return sorted((tmp_path / out_dir).glob("*.docx"))


# ---- QC_SCRIPT: advisory by default, blocking opt-in ----

def test_qc_script_failure_is_advisory_by_default(tmp_path):
    qc = tmp_path / "always_fail_qc.py"
    qc.write_text(ALWAYS_FAIL_SCRIPT, encoding="utf-8")
    src, rc, out = _render(tmp_path, "out-qc-advisory", "--qc", env_extra={"QC_SCRIPT": str(qc)})
    assert rc == 0, out
    assert "FAKE-GATE: simulated finding" in out
    assert "advisory, not blocking" in out
    assert len(_docx_files(tmp_path, "out-qc-advisory")) == 1


def test_qc_blocking_env_var_stops_the_render(tmp_path):
    qc = tmp_path / "always_fail_qc.py"
    qc.write_text(ALWAYS_FAIL_SCRIPT, encoding="utf-8")
    src, rc, out = _render(
        tmp_path, "out-qc-blocking-env", "--qc",
        env_extra={"QC_SCRIPT": str(qc), "QC_BLOCKING": "1"},
    )
    assert rc != 0, out
    assert "render-doc complete" not in out
    assert len(_docx_files(tmp_path, "out-qc-blocking-env")) == 0


def test_qc_blocking_flag_stops_the_render(tmp_path):
    qc = tmp_path / "always_fail_qc.py"
    qc.write_text(ALWAYS_FAIL_SCRIPT, encoding="utf-8")
    src, rc, out = _render(
        tmp_path, "out-qc-blocking-flag", "--qc-blocking", env_extra={"QC_SCRIPT": str(qc)},
    )
    assert rc != 0, out
    assert "render-doc complete" not in out
    assert len(_docx_files(tmp_path, "out-qc-blocking-flag")) == 0


def test_qc_blocking_flag_implies_qc_even_without_bare_qc(tmp_path):
    """--qc-blocking alone (no separate --qc) must still run the hook."""
    qc = tmp_path / "always_fail_qc.py"
    qc.write_text(ALWAYS_FAIL_SCRIPT, encoding="utf-8")
    src, rc, out = _render(
        tmp_path, "out-qc-blocking-only", "--qc-blocking", env_extra={"QC_SCRIPT": str(qc)},
    )
    assert "Pre-render QC" in out
    assert rc != 0, out


# ---- POSTRENDER_GATE_SCRIPT: fires post-render with the finished docx path ----

def test_postrender_gate_not_invoked_without_flag(tmp_path):
    gate = tmp_path / "record_arg_gate.py"
    gate.write_text(RECORD_ARG_SCRIPT, encoding="utf-8")
    marker = tmp_path / "called-with.txt"
    src, rc, out = _render(
        tmp_path, "out-postrender-off", env_extra={"POSTRENDER_GATE_SCRIPT": str(gate)},
    )
    assert rc == 0, out
    assert not marker.exists()


def test_postrender_gate_fires_with_finished_docx_path(tmp_path):
    gate = tmp_path / "record_arg_gate.py"
    gate.write_text(RECORD_ARG_SCRIPT, encoding="utf-8")
    marker = tmp_path / "called-with.txt"
    src, rc, out = _render(
        tmp_path, "out-postrender-fires", "--postrender-gate",
        env_extra={"POSTRENDER_GATE_SCRIPT": str(gate)},
    )
    assert rc == 0, out
    assert marker.exists()
    called_with = Path(marker.read_text(encoding="utf-8").strip())
    docx_files = _docx_files(tmp_path, "out-postrender-fires")
    assert len(docx_files) == 1
    # the hook receives the real, finished docx path (RECORD_ARG_SCRIPT itself
    # also asserts the arg is an existing .docx before exiting 0)
    assert called_with.resolve() == docx_files[0].resolve()
    # fired after render (pandoc already ran), before the completion banner
    assert out.index("Running pandoc") < out.index("Post-render content-safety gate")
    assert out.index("Post-render content-safety gate") < out.index("render-doc complete")


def test_postrender_gate_blocks_by_default(tmp_path):
    gate = tmp_path / "always_fail_gate.py"
    gate.write_text(ALWAYS_FAIL_SCRIPT, encoding="utf-8")
    src, rc, out = _render(
        tmp_path, "out-postrender-blocking", "--postrender-gate",
        env_extra={"POSTRENDER_GATE_SCRIPT": str(gate)},
    )
    assert rc != 0, out
    assert "render-doc complete" not in out
    # the docx WAS produced (the gate runs post-render) even though the run fails
    assert len(_docx_files(tmp_path, "out-postrender-blocking")) == 1


def test_postrender_gate_advisory_opt_out(tmp_path):
    gate = tmp_path / "always_fail_gate.py"
    gate.write_text(ALWAYS_FAIL_SCRIPT, encoding="utf-8")
    src, rc, out = _render(
        tmp_path, "out-postrender-advisory", "--postrender-gate",
        env_extra={"POSTRENDER_GATE_SCRIPT": str(gate), "POSTRENDER_GATE_ADVISORY": "1"},
    )
    assert rc == 0, out
    assert "FAKE-GATE: simulated finding" in out
    assert "advisory, not blocking" in out
    assert "render-doc complete" in out
