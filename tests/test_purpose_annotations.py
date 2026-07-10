"""
Empirical verification for issue #77's core render-risk claim: an
`<!-- PURPOSE: ... -->` (or any HTML comment) placed in a markdown source
never survives into a rendered artefact, on EITHER render path this repo
ships (DOCX via pandoc, PDF via pandoc's typst writer + typst compile).

This is deliberately NOT an assumption-based test. It drives the REAL
render pipelines (subprocess pandoc / typst, the same `render docx` /
`pdf/typst_backend.py` code paths a user hits) and asserts the marker
string is absent from the actual output, so a future pandoc/typst upgrade
that changed raw-HTML handling would be caught here, not discovered later
in a leaked render. Skips gracefully (not a hard failure) on a host missing
pandoc/typst, matching this repo's existing integration-test convention
(tests/test_render_doc_provenance.py, tests/test_typst_backend.py).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "pdf"))

RENDER_PY = REPO_ROOT / "render.py"
HAVE_PANDOC = shutil.which("pandoc") is not None
HAVE_TYPST = shutil.which("typst") is not None

# A marker unlikely to appear in any pandoc/typst boilerplate, so its total
# absence from rendered output is unambiguous.
MARKER = "PURPOSE-ANNOTATION-MARKER-7d3f1c"

SOURCE = f"""---
title: Purpose Annotation No-Op Check
---

<!-- PURPOSE: {MARKER} this paragraph establishes the baseline before the
     tradeoff below -->

# Overview

A plain narrative paragraph with no special markup at all.

<!-- PURPOSE: {MARKER} states the tradeoff explicitly so a later editor can
     tell this is load-bearing, not incidental -->

## Tradeoff

Another plain paragraph, this time under a subheading, immediately preceded
by its own purpose comment.
"""


def _docx_body_text(docx_path: Path) -> str:
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.S))


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_purpose_comment_absent_from_real_docx_render(tmp_path):
    src = tmp_path / "doc.md"
    src.write_text(SOURCE, encoding="utf-8")
    env = {**os.environ, "OUTPUT_DIR": str(tmp_path / "out")}
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "docx", str(src)],
        capture_output=True, text=True, timeout=180, env=env, cwd=tmp_path,
    )
    combined = result.stdout + result.stderr
    if result.returncode == 3 and ("pandoc not found" in combined or "bash not found" in combined):
        pytest.skip("render engines not installed on this host: " + combined.strip()[:120])
    assert result.returncode == 0, combined

    docx_files = sorted((tmp_path / "out").glob("*.docx"))
    assert len(docx_files) == 1, combined
    body_text = _docx_body_text(docx_files[0])

    # The marker (and the comment syntax itself) must be completely absent:
    # pandoc parses `<!-- ... -->` as a raw-HTML AST node the docx writer
    # never emits.
    assert MARKER not in body_text
    assert "PURPOSE" not in body_text
    assert "<!--" not in body_text
    # the surrounding narrative content DID render, so this is a targeted
    # comment-drop, not e.g. the whole document silently failing to render
    assert "plain narrative paragraph" in body_text
    assert "Tradeoff" in body_text


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_purpose_comment_absent_from_pandoc_typst_markup(tmp_path):
    # The PDF path: pandoc's OWN markdown reader feeds its typst WRITER (the
    # same reader as the docx path -- pdf/typst_backend.py never lets typst
    # parse the original markdown itself). Checking pandoc's typst-markup
    # output is the direct empirical checkpoint: if the marker is not here,
    # it structurally cannot reach the compiled PDF, since typst only ever
    # sees this text.
    import typst_backend as tb  # pdf/typst_backend.py

    src = tmp_path / "doc.md"
    src.write_text(SOURCE, encoding="utf-8")
    pandoc = tb.find_pandoc()
    typst_markup = tb.md_to_typst(src, pandoc)

    assert MARKER not in typst_markup
    assert "PURPOSE" not in typst_markup
    assert "<!--" not in typst_markup
    assert "plain narrative paragraph" in typst_markup
    assert "Tradeoff" in typst_markup


@pytest.mark.skipif(not (HAVE_PANDOC and HAVE_TYPST), reason="needs pandoc + typst")
def test_purpose_comment_absent_from_compiled_pdf_pipeline(tmp_path):
    # End-to-end: the full render_pdf() pipeline (pandoc -> typst compile)
    # completes cleanly with purpose comments present in the source (no
    # crash, no error), producing a real PDF -- the comment is inert, not
    # merely stripped-but-otherwise-disruptive.
    import typst_backend as tb  # pdf/typst_backend.py

    src = tmp_path / "doc.md"
    src.write_text(SOURCE, encoding="utf-8")
    out = tb.render_pdf(src, tmp_path / "doc.pdf", title="Purpose Annotation Check")
    assert out.is_file()
    assert out.read_bytes()[:5] == b"%PDF-"
