"""
Regression test for #120: `render docx --pdf`'s own --help text used to read
"(Word-COM on Windows, else soffice)", implying automatic Word-COM conversion
on Windows with no consumer setup required. The actual gate needs
PDF_CONVERTER_PS1 configured and no such script is bundled. This test locks in
the corrected, honest wording so it can't silently drift back to the overclaim.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_PY = REPO_ROOT / "render.py"


def test_pdf_help_names_pdf_converter_ps1_not_automatic_word_com():
    # Go through render.py's own dispatcher, not a raw "bash" invocation: this
    # repo already works around a real Windows footgun where PATH's first
    # `bash` resolves to the System32 WSL stub rather than a real POSIX shell
    # (see render.py's own _find_bash()); render.py docx --help already
    # exercises that correctly-resolved path.
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "docx", "--help"],
        capture_output=True, text=True, timeout=30,
    )
    out = result.stdout + result.stderr
    assert "PDF_CONVERTER_PS1" in out
    # the old overclaim, verbatim, must not survive
    assert "(Word-COM on Windows, else soffice)" not in out
