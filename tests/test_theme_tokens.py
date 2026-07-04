"""
Tests for tokens/gen/theme_tokens.py (issue #32): the engine-agnostic theme
descriptor (brand.yaml [theme] -> chrome.typ), plus its variant inheritance and
its consumption by the typst PDF backend.

Unit tests (no binaries) cover variant resolution, the emitted chrome.typ shape,
and slot/role handling. A skipif-guarded integration test proves a variant
actually changes the rendered PDF.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tokens" / "gen"))
sys.path.insert(0, str(REPO_ROOT / "pdf"))

import theme_tokens as tt  # noqa: E402
from _common import load_tokens  # noqa: E402

HAVE_TYPST = shutil.which("typst") is not None
HAVE_PANDOC = shutil.which("pandoc") is not None


def _tokens():
    return load_tokens(None)  # the neutral default brand.yaml, which ships a [theme]


# ---------------------------------------------------------- variant resolve --

def test_resolve_base():
    t = tt.resolve_theme(_tokens(), "base")
    assert t["heading_role"] == "accent" and t["title_role"] == "primary"
    assert t["margin_cm"] == {"x": 2.2, "top": 2.6, "bottom": 2.4}


def test_resolve_default_is_base():
    assert tt.resolve_theme(_tokens()) == tt.resolve_theme(_tokens(), "base")


def test_resolve_financial_inherits_and_overrides():
    base = tt.resolve_theme(_tokens(), "base")
    fin = tt.resolve_theme(_tokens(), "financial")
    assert fin["heading_role"] == "primary"          # overridden
    assert fin["title_role"] == base["title_role"]   # inherited
    assert fin["margin_cm"] == base["margin_cm"]      # inherited


def test_resolve_unknown_variant_raises():
    with pytest.raises(KeyError, match="unknown theme variant"):
        tt.resolve_theme(_tokens(), "does-not-exist")


# ------------------------------------------------------------- chrome.typ --

def test_render_theme_shape():
    typ = tt.render_theme(_tokens(), "base")
    assert "#let chrome = (" in typ
    assert 'heading-role: "accent"' in typ
    assert 'title-role: "primary"' in typ
    assert "margin: (x: 2.2cm, top: 2.6cm, bottom: 2.4cm)" in typ
    assert 'header: (left: "org", right: "title")' in typ
    assert 'footer: (left: "date", right: "pagenumber")' in typ
    assert "body-pt: 10.5" in typ and "justify: true" in typ


def test_render_theme_component_roles():
    typ = tt.render_theme(_tokens(), "base")
    assert 'callout: (fill-role: "fill", border-role: "accent")' in typ
    assert 'statement: (rule-role: "primary", heading-role: "accent")' in typ


def test_render_theme_financial_differs():
    assert 'heading-role: "primary"' in tt.render_theme(_tokens(), "financial")


def test_variant_overrides_statement_heading_keeps_rule():
    fin = tt.resolve_theme(_tokens(), "financial")
    assert fin["statement"]["heading_role"] == "primary"   # overridden
    assert fin["statement"]["rule_role"] == "primary"       # inherited from base
    # base callout is inherited untouched
    assert fin["callout"] == tt.resolve_theme(_tokens(), "base")["callout"]


def test_slot_none_renders_none():
    assert tt._slot(None) == "none"
    assert tt._slot("none") == "none"
    assert tt._slot("org") == '"org"'


def test_render_theme_handles_none_slot():
    tokens = _tokens()
    tokens["theme"]["base"]["header"] = {"left": None, "right": "title"}
    typ = tt.render_theme(tokens, "base")
    assert "header: (left: none, right: \"title\")" in typ


# ---------------------------------------------------- integration (real) --

@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_backend_variant_changes_pdf(tmp_path):
    import typst_backend as tb

    md = tmp_path / "doc.md"
    md.write_text("# Heading\n\nBody.\n", encoding="utf-8")
    base = tb.render_pdf(md, tmp_path / "base.pdf", title="T", variant="base")
    fin = tb.render_pdf(md, tmp_path / "fin.pdf", title="T", variant="financial")
    assert base.is_file() and fin.is_file()
    # different heading colour -> different compiled bytes
    assert base.read_bytes() != fin.read_bytes()


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_variant_restyles_statement_block(tmp_path):
    import typst_backend as tb

    md = tmp_path / "d.md"
    md.write_text("::: statement\n- heading | Income\n- item | Dues | 10\n- total | Total | 10\n:::\n",
                  encoding="utf-8")
    base = tb.render_pdf(md, tmp_path / "b.pdf", title="T", variant="base")
    fin = tb.render_pdf(md, tmp_path / "f.pdf", title="T", variant="financial")
    # financial restyles the ledger section headings -> different bytes
    assert base.read_bytes() != fin.read_bytes()


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_backend_unknown_variant_errors(tmp_path):
    import typst_backend as tb

    md = tmp_path / "doc.md"
    md.write_text("# Hi\n", encoding="utf-8")
    with pytest.raises(tb.TypstBackendError, match="unknown theme variant"):
        tb.render_pdf(md, tmp_path / "x.pdf", variant="nope")
