"""
Integration tests for the D11/D14 provenance wiring in container/render-doc.sh:
a default render embeds provenance from the canonical source; a render projected
under a profile with strip_provenance: true is scrubbed instead; PROVENANCE=off
skips both. Runs the REAL pipeline (bash + pandoc), so it skips gracefully on
hosts without those engines (CI runners without pandoc; the unit-level strip
behaviour is covered engine-free in test_provenance.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from roundtrip import provenance  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"

SOURCE = """---
title: Provenance Wiring Check
version: v3
---

# Overview

Plain paragraph.

::: {.block clearance="secret"}
Internal-only line.
:::
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
    assert result.returncode == 0, combined
    docx_files = sorted((tmp_path / out_dir).glob("*.docx"))
    assert len(docx_files) == 1, combined
    return src, docx_files[0], combined


def test_default_render_embeds_provenance_from_canonical_source(tmp_path):
    src, artifact, out = _render(tmp_path, "out-default")
    prov = provenance.extract(artifact)
    assert prov is not None
    assert prov.source_uid in src.read_text(encoding="utf-8")  # uid persisted in frontmatter
    assert "embedding source identity" in out


def test_strip_profile_render_carries_no_provenance(tmp_path):
    src, artifact, out = _render(tmp_path, "out-public", "--project", "public-release")
    assert provenance.extract(artifact) is None
    assert "stripping, not embedding" in out
    # and the strip really was about provenance, not a failed render:
    from docx import Document

    text = "\n".join(p.text for p in Document(str(artifact)).paragraphs)
    assert "Plain paragraph." in text
    assert "Internal-only line." not in text  # the projection gate held too


def test_provenance_off_skips_both_paths(tmp_path):
    src, artifact, out = _render(tmp_path, "out-off", env_extra={"PROVENANCE": "off"})
    assert provenance.extract(artifact) is None
    assert "embedding source identity" not in out
    assert "renderfact_uid" not in src.read_text(encoding="utf-8")  # source untouched
