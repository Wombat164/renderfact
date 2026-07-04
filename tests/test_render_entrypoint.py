"""
Tests for render.py -- the unified entry point (execution-plan chunk 0.1 + 0.2).

Covers the DISPATCH mechanism only (mode routing, passthrough, error handling)
-- not the underlying render engines (mmdc/d2/pandoc/etc.), which need real
binaries and are exercised separately. Run: pytest tests/test_render_entrypoint.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_PY = REPO_ROOT / "render.py"


def run_render(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, **env_extra} if env_extra else None
    return subprocess.run(
        [sys.executable, str(RENDER_PY), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def test_unknown_mode_fails_cleanly():
    result = run_render("bogus-mode")
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_no_mode_shows_usage():
    result = run_render()
    assert result.returncode != 0
    assert "render" in (result.stderr + result.stdout).lower()


def test_docx_mode_dispatches_to_render_doc_sh():
    # No source given. Dispatch is proven by reaching one of render-doc.sh's
    # OWN early errors; WHICH one depends on what the host has installed
    # (pandoc/python present: the arg check fires; absent: the tool checks
    # fire first), so accept the set instead of encoding one machine's
    # environment (first caught by CI: the dev box reached the arg check,
    # runners without pandoc exited earlier). Since the P1.2 generalization,
    # render-doc.sh needs no VAULT_ROOT or any other env to get this far.
    result = run_render("docx")
    out = result.stdout + result.stderr
    assert result.returncode in (2, 3), out
    assert any(
        marker in out
        for marker in ("<source.md> is required", "pandoc not found", "python not found")
    ), out
    # ...and that it was NOT render.py's own dispatcher failing:
    assert "render-doc.sh not found" not in out
    assert "bash not found" not in out


def test_docx_mode_help_shows_render_doc_sh_usage():
    # Issue #26: -h/--help must be intercepted by render-doc.sh BEFORE the
    # source-existence check. Previously '--help' was taken as the source path
    # and dead-ended with "ERROR: source not found: --help" (rc 2).
    result = run_render("docx", "--help")
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "Usage: render-doc.sh" in out
    assert "source not found" not in out


def test_diagram_mode_dispatches_to_lint_render():
    # No input files -> lint/render.py's own "no input files found" error,
    # proving the dispatch reached it in-process.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        empty_dir = Path(tmp) / "empty"
        empty_dir.mkdir()
        result = run_render("diagram", str(empty_dir))
        assert result.returncode == 2
        assert "no input files found" in (result.stdout + result.stderr)


def test_diagram_mode_help_shows_lint_render_own_parser():
    result = run_render("diagram", "--help")
    assert result.returncode == 0
    assert "Diagram Render Orchestrator" in result.stdout


def test_doctor_mode_reports_and_never_fails(_deep_coverage_in="tests/test_doctor.py"):
    result = run_render("doctor")
    assert result.returncode == 0  # report-only is the D10 contract
    assert "doctor:" in result.stdout
    assert "never fails closed" in result.stdout


def test_init_ai_mode_dispatches_to_contracts_init_ai():
    # Real subprocess dispatch (not the direct unit tests in test_init_ai.py) --
    # proves render.py's own mode routing reaches contracts/init_ai.py.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        result = run_render("init-ai", "--assistant", "claude", "--target-dir", tmp)
        assert result.returncode == 0
        assert (Path(tmp) / ".claude" / "skills" / "renderfact" / "SKILL.md").exists()


def test_copy_paste_mode_dispatches_end_to_end_with_simulated_paste_back():
    # Real subprocess dispatch, non-interactive (all flags supplied so it never
    # calls input()), simulated paste-back via stdin -- proves render.py's mode
    # routing reaches contracts/copy_paste.py and the whole loop actually works,
    # not just the direct unit tests in test_copy_paste.py.
    #
    # run_copy_paste() scratch-writes to REPO_ROOT (not cwd) -- see render.py --
    # so this test cleans that file up itself rather than relying on isolation.
    pasted_reply = (
        '{"status": "OK", "findings": [], "summary": "Clean layout.", '
        '"reviewer_mode": "harness"}\nEND\n'  # deliberately wrong mode -- proves the force-override
    )
    scratch_file = REPO_ROOT / ".renderfact-copy-paste-prompt.txt"
    try:
        result = subprocess.run(
            [
                sys.executable, str(RENDER_PY), "copy-paste", "vision-review",
                "--tier", "operator-handoff", "--image", "renders/hero.png",
                "--metrics-json", '{"edge_crossings": 1}',
            ],
            input=pasted_reply,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert '"reviewer_mode": "copy-paste"' in result.stdout
        assert scratch_file.exists()
    finally:
        scratch_file.unlink(missing_ok=True)
