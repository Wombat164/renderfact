"""
Integration tests for the table of contents opt-out (issue #99): container/render-doc.sh
used to hardcode `--toc --toc-depth=2` into PANDOC_ARGS unconditionally, with no way to
disable it, a fidelity problem for short documents that never had a table of contents in
the original.

Two opt-out paths, either one sufficient:
1. `--no-toc` CLI flag.
2. `toc: false` top-level key in the yaml passed via --template-profile.

Default stays on (today's behavior): a render with neither path present still gets a
table of contents, as a regression guard.

Runs the REAL pipeline (bash + pandoc), same pattern as test_render_doc_gate_hooks.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RENDER_PY = REPO_ROOT / "render.py"

SOURCE = """---
title: Toc Opt Out Check
version: v1
---

# Heading One

Plain paragraph, nothing sensitive.

# Heading Two

More plain text.
"""

TEMPLATE_PROFILE_NO_TOC = """
toc: false
"""


def _render(tmp_path: Path, out_dir: str, *extra: str, env_extra: dict | None = None):
    src = tmp_path / "toc-check.md"
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


def _has_toc_field(docx: Path) -> bool:
    """A pandoc --toc render carries a `TOC \\o ...` field instruction inside a
    docPartGallery "Table of Contents" w:sdt in word/document.xml. Absence of the
    literal field instruction is a reliable proxy for "no table of contents"."""
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return "TOC \\o" in xml


# ---- regression guard: default behavior (today's on-by-default ToC) is unchanged ----

def test_default_render_still_gets_a_toc(tmp_path):
    src, rc, out = _render(tmp_path, "out-toc-default")
    assert rc == 0, out
    docx_files = _docx_files(tmp_path, "out-toc-default")
    assert len(docx_files) == 1
    assert _has_toc_field(docx_files[0]), "default render must still carry a ToC"


# ---- opt-out path 1: --no-toc CLI flag ----

def test_no_toc_flag_omits_the_toc(tmp_path):
    src, rc, out = _render(tmp_path, "out-toc-flag", "--no-toc")
    assert rc == 0, out
    assert "Table of contents: disabled" in out
    docx_files = _docx_files(tmp_path, "out-toc-flag")
    assert len(docx_files) == 1
    assert not _has_toc_field(docx_files[0]), "--no-toc must omit the ToC"


# ---- opt-out path 2: toc: false in the --template-profile yaml ----

def test_template_profile_toc_false_omits_the_toc(tmp_path):
    tp = tmp_path / "template-profile.yaml"
    tp.write_text(TEMPLATE_PROFILE_NO_TOC, encoding="utf-8")
    src, rc, out = _render(tmp_path, "out-toc-profile", "--template-profile", str(tp))
    assert rc == 0, out
    assert "Table of contents: disabled" in out
    docx_files = _docx_files(tmp_path, "out-toc-profile")
    assert len(docx_files) == 1
    assert not _has_toc_field(docx_files[0]), "toc: false in --template-profile must omit the ToC"


def test_template_profile_without_toc_key_keeps_default_on(tmp_path):
    """A template-profile.yaml that does not mention `toc` at all must not
    accidentally disable it (default-true, unknown keys ignored)."""
    tp = tmp_path / "template-profile.yaml"
    tp.write_text("font: Arial\n", encoding="utf-8")
    src, rc, out = _render(tmp_path, "out-toc-profile-unset", "--template-profile", str(tp))
    assert rc == 0, out
    docx_files = _docx_files(tmp_path, "out-toc-profile-unset")
    assert len(docx_files) == 1
    assert _has_toc_field(docx_files[0])
