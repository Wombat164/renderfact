"""
Regression tests for issue #69: `[[target|Display Text]]` bracket wikilinks
must resolve to their display text in rendered output, on every render path
that reads renderfact markdown.

This file covers the DOCX path (container/render-doc.sh, invoked via `render
docx`), the real end-to-end pipeline (bash + pandoc), not a mock and not a
Lua filter run in isolation. The PDF-path equivalent
(pdf/typst_backend.py::render_pdf, via `render pdf`) lives in
tests/test_typst_backend.py next to its other real-render tests.

Both paths now source their pandoc `--from` value from the single shared
pandoc_markdown.MARKDOWN_FROM constant (see pandoc_markdown.py and
tests/test_pandoc_markdown.py), so this file is what proves the constant
actually reaches the DOCX pipeline at runtime, not just that the constant
itself is correct.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_PY = REPO_ROOT / "render.py"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_text(docx_path: Path) -> str:
    """All <w:t> run text in document.xml, concatenated: enough to check a
    phrase survived (or a literal bracket did not), without a python-docx
    dependency for this one check (mirrors lint/render_qa.py's own approach)."""
    with zipfile.ZipFile(docx_path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    import re
    return "".join(re.findall(rf"<w:t[^>]*>(.*?)</w:t>", xml, re.S))


def test_docx_render_resolves_wikilink_display_text(tmp_path):
    src = tmp_path / "wiki.md"
    src.write_text(
        "---\ntitle: Wikilink Check\n---\n\n"
        "# Wikilink check\n\nSee [[some-target|Display Text]] for detail.\n",
        encoding="utf-8",
    )
    env = {**os.environ, "OUTPUT_DIR": str(tmp_path / "out")}
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "docx", str(src)],
        capture_output=True, text=True, timeout=120, env=env, cwd=tmp_path,
    )
    combined = result.stdout + result.stderr
    if result.returncode == 3 and ("pandoc not found" in combined or "bash not found" in combined
                                    or "python not found" in combined):
        pytest.skip("render engines not installed on this host: " + combined.strip()[:160])
    assert result.returncode == 0, combined

    docx_files = sorted((tmp_path / "out").glob("*.docx"))
    assert len(docx_files) == 1, combined
    text = _docx_text(docx_files[0])
    assert "Display Text" in text
    assert "[[" not in text and "]]" not in text
