"""
Tests for the #33 first-class semantic blocks: pdf/filters/semantic-blocks.lua
(fenced div -> typst function call) + pdf/theme/blocks.typ (the typst render).

Unit tests (no binaries) cover the backend wiring (assets shipped, blocks
imported, filter passed). Filter tests run pandoc and assert the emitted typst
calls (skipped without pandoc). A full-render integration test compiles a
document using all three blocks (skipped without typst + pandoc).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pdf"))

import typst_backend as tb  # noqa: E402

HAVE_TYPST = shutil.which("typst") is not None
HAVE_PANDOC = shutil.which("pandoc") is not None

ALL_BLOCKS = """# Minutes

::: attendance
- present | A. Janssens
- proxy | C. De Wit, via A. Janssens
- quorum | 3/5 present: quorum met
:::

::: statement
- heading | Income
- item | Member dues | EUR 8.045,77
- subtotal | Total income | EUR 8.045,77
- rule
- total | Balance | EUR 1.510,53
:::

::: signatures
- A. Janssens | Chair of the general assembly
- B. Peeters | Secretary
:::
"""


def _md_to_typst(md_text: str, tmp_path: Path) -> str:
    md = tmp_path / "d.md"
    md.write_text(md_text, encoding="utf-8")
    return tb.md_to_typst(md, shutil.which("pandoc"))


# ---------------------------------------------------------------- wiring --

def test_backend_ships_block_assets():
    assert tb.BLOCKS_TYP.is_file()
    assert tb.SEMANTIC_FILTER.is_file()


def test_compose_main_imports_blocks():
    main = tb.compose_main("body", title=None, subtitle=None, org=None, date=None, paper="a4")
    assert '#import "blocks.typ": *' in main


def test_md_to_typst_passes_semantic_filter(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(tb.subprocess, "run", fake_run)
    md = tmp_path / "d.md"
    md.write_text("# x\n", encoding="utf-8")
    tb.md_to_typst(md, "pandoc")
    assert "--lua-filter" in captured["cmd"]
    assert str(tb.SEMANTIC_FILTER) in captured["cmd"]


# ------------------------------------------------------- filter (pandoc) --

@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_signatures_filter(tmp_path):
    out = _md_to_typst("::: signatures\n- Alice | Chair\n- Bob | Sec\n:::\n", tmp_path)
    assert "#signatures((" in out
    assert '("Alice", "Chair")' in out and '("Bob", "Sec")' in out


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_attendance_filter(tmp_path):
    out = _md_to_typst("::: attendance\n- present | Alice\n- quorum | 3/5\n:::\n", tmp_path)
    assert "#attendance((" in out
    assert 'kind: "present"' in out and 'text: "Alice"' in out and 'kind: "quorum"' in out


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_statement_filter(tmp_path):
    out = _md_to_typst(
        "::: statement\n- heading | Income\n- item | Dues | 100\n- rule\n- total | Balance | 100\n:::\n",
        tmp_path)
    assert "#statement((" in out
    assert 'kind: "heading"' in out and 'kind: "item"' in out and 'label: "Dues"' in out
    assert 'amount: "100"' in out and 'kind: "rule"' in out and 'kind: "total"' in out


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_plain_document_is_passthrough(tmp_path):
    out = _md_to_typst("# Title\n\nJust prose, no blocks.\n", tmp_path)
    assert "#signatures" not in out and "#attendance" not in out and "#statement" not in out


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_signatures_missing_role_is_empty_string(tmp_path):
    out = _md_to_typst("::: signatures\n- Solo Name\n:::\n", tmp_path)
    assert '("Solo Name", "")' in out


# -------------------------------------------------- render (typst+pandoc) --

@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_render_with_all_blocks_compiles(tmp_path):
    md = tmp_path / "vme.md"
    md.write_text(ALL_BLOCKS, encoding="utf-8")
    out = tb.render_pdf(md, tmp_path / "vme.pdf", title="Minutes", org="Org", date="2025-01-01")
    assert out.is_file() and out.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_render_without_blocks_still_compiles(tmp_path):
    md = tmp_path / "plain.md"
    md.write_text("# Hi\n\nJust text.\n", encoding="utf-8")
    out = tb.render_pdf(md, tmp_path / "p.pdf", title="Hi")
    assert out.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_signature_labels_follow_locale(tmp_path):
    md = tmp_path / "s.md"
    md.write_text("::: signatures\n- A. Name | Chair\n:::\n", encoding="utf-8")
    en = tb.render_pdf(md, tmp_path / "en.pdf", title="T", locale="en")
    nl = tb.render_pdf(md, tmp_path / "nl.pdf", title="T", locale="nl-BE")
    assert en.read_bytes() != nl.read_bytes()  # Signature/Date vs Handtekening/Datum


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_demo_agm_showcase_renders(tmp_path):
    src = REPO_ROOT / "demo" / "source" / "agm-minutes.md"
    brand = REPO_ROOT / "demo" / "skin" / "brand.yaml"
    if not (src.is_file() and brand.is_file()):
        pytest.skip("demo fixtures absent")
    out = tb.render_pdf(src, tmp_path / "agm.pdf", brand=str(brand), variant="financial",
                        locale="en", title="AGM", org="Meridian Rail Infrastructure")
    assert out.read_bytes()[:5] == b"%PDF-"
