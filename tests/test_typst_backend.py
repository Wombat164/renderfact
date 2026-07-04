"""
Tests for pdf/typst_backend.py (issue #31): the layout-native PDF backend
(markdown -> pandoc typst writer -> typst -> PDF), a peer of the DOCX path.

Unit tests (no binaries) cover tool resolution, error mapping, and main.typ
composition. An integration test actually compiles a PDF, skipped when typst or
pandoc is absent (as on CI runners). A dispatch test proves `render pdf` routes.
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

RENDER_PY = REPO_ROOT / "render.py"
HAVE_TYPST = shutil.which("typst") is not None
HAVE_PANDOC = shutil.which("pandoc") is not None


# ----------------------------------------------------------- typst literals --

def test_typ_str_none():
    assert tb._typ_str(None) == "none"


def test_typ_str_escapes():
    assert tb._typ_str('a "b" \\c') == '"a \\"b\\" \\\\c"'


def test_compose_main_shape():
    main = tb.compose_main("= Body\n", title="T", subtitle=None, org="Org", date="2025", paper="a4")
    assert '#import "theme.typ": conf' in main
    assert "#show: conf.with(" in main
    assert 'title: "T"' in main and 'org: "Org"' in main and 'subtitle: none' in main
    assert 'paper: "a4"' in main
    assert main.rstrip().endswith("= Body")


# --------------------------------------------------------------- tool lookup --

def test_resolve_env_override(monkeypatch):
    monkeypatch.setenv("TYPST", "/custom/typst")
    assert tb._resolve("typst", "TYPST") == "/custom/typst"


def test_find_typst_missing_raises(monkeypatch):
    monkeypatch.delenv("TYPST", raising=False)
    monkeypatch.setattr(tb.shutil, "which", lambda _b: None)
    monkeypatch.setattr(tb.sys, "platform", "linux")
    with pytest.raises(tb.TypstBackendError, match="typst not found"):
        tb.find_typst()


def test_find_pandoc_missing_raises(monkeypatch):
    monkeypatch.delenv("PANDOC", raising=False)
    monkeypatch.setattr(tb.shutil, "which", lambda _b: None)
    monkeypatch.setattr(tb.sys, "platform", "linux")
    with pytest.raises(tb.TypstBackendError, match="pandoc not found"):
        tb.find_pandoc()


# --------------------------------------------------------------- error paths --

def test_md_to_typst_error_maps(monkeypatch, tmp_path):
    md = tmp_path / "x.md"
    md.write_text("# hi\n", encoding="utf-8")

    def _fail(*a, **k):
        return subprocess.CompletedProcess(a, 1, stdout="", stderr="pandoc boom")
    monkeypatch.setattr(tb.subprocess, "run", _fail)
    with pytest.raises(tb.TypstBackendError, match="pandoc boom"):
        tb.md_to_typst(md, "pandoc")


def test_render_pdf_missing_source(tmp_path):
    with pytest.raises(tb.TypstBackendError, match="source not found"):
        tb.render_pdf(tmp_path / "nope.md", typst="typst", pandoc="pandoc")


def test_render_pdf_missing_theme(tmp_path):
    md = tmp_path / "x.md"
    md.write_text("# hi\n", encoding="utf-8")
    with pytest.raises(tb.TypstBackendError, match="theme not found"):
        tb.render_pdf(md, tmp_path / "out.pdf", theme=tmp_path / "nope.typ",
                      typst="typst", pandoc="pandoc")


# ------------------------------------------------------------- font paths --

def test_compile_cmd_font_paths():
    from pathlib import Path as P
    cmd = tb._compile_cmd("typst", P("/w"), P("/w/main.typ"), P("/w/out.pdf"),
                          "pdf", 144, ["/fonts/a", "/fonts/b"])
    assert cmd.count("--font-path") == 2
    assert "/fonts/a" in cmd and "/fonts/b" in cmd


def test_compile_cmd_png_no_fonts():
    from pathlib import Path as P
    cmd = tb._compile_cmd("typst", P("/w"), P("/w/main.typ"), P("/w/p-{0p}.png"),
                          "png", 200, None)
    assert "--font-path" not in cmd
    assert "--format" in cmd and "png" in cmd and "200" in cmd


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_render_with_font_path_compiles(tmp_path):
    (tmp_path / "fonts").mkdir()
    (tmp_path / "doc.md").write_text("# Hi\n\nText.\n", encoding="utf-8")
    out = tb.render_pdf(tmp_path / "doc.md", tmp_path / "doc.pdf", title="Hi",
                        font_paths=[str(tmp_path / "fonts")])
    assert out.read_bytes()[:5] == b"%PDF-"


# --------------------------------------------------------------- images --

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_stage_images_rewrites_and_copies(tmp_path):
    (tmp_path / "logo.png").write_bytes(_PNG)
    work = tmp_path / "work"
    work.mkdir()
    body = 'a #figure(image("logo.png", alt: "l")) b'
    out = tb.stage_images(body, tmp_path, work)
    assert 'image("_img/1.png"' in out
    assert (work / "_img" / "1.png").is_file()


def test_stage_images_dedupes_repeated_ref(tmp_path):
    (tmp_path / "logo.png").write_bytes(_PNG)
    work = tmp_path / "work"; work.mkdir()
    body = 'image("logo.png") ... image("logo.png")'
    out = tb.stage_images(body, tmp_path, work)
    assert out.count('image("_img/1.png"') == 2  # same staged file reused


def test_stage_images_leaves_urls_and_missing(tmp_path):
    work = tmp_path / "work"; work.mkdir()
    body = 'image("https://x/y.png") image("gone.png")'
    out = tb.stage_images(body, tmp_path, work)
    assert 'image("https://x/y.png")' in out and 'image("gone.png")' in out


def test_stage_images_jail_blocks_escape(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    (tmp_path / "secret.png").write_bytes(_PNG)
    work = tmp_path / "work"; work.mkdir()
    body = 'image("../secret.png")'
    out = tb.stage_images(body, root, work, image_root=root)
    assert 'image("../secret.png")' in out  # not staged
    assert not (work / "_img").exists()


# ---------------------------------------------------------- integration (real) --

# ------------------------------------------------------------- projection --

def test_project_requires_profiles(tmp_path):
    src = tmp_path / "s.md"
    src.write_text("# x\n", encoding="utf-8")
    with pytest.raises(tb.TypstBackendError, match="requires --profiles"):
        tb._project_markdown(src, "some-profile", None)


def test_project_missing_config(tmp_path):
    src = tmp_path / "s.md"
    src.write_text("# x\n", encoding="utf-8")
    with pytest.raises(tb.TypstBackendError, match="profiles config not found"):
        tb._project_markdown(src, "p", tmp_path / "nope.yaml")


def test_project_unknown_profile():
    src = REPO_ROOT / "demo" / "source" / "signalling-it-refresh.md"
    cfg = REPO_ROOT / "demo" / "profiles.yaml"
    if not (src.is_file() and cfg.is_file()):
        pytest.skip("demo fixtures absent")
    with pytest.raises(tb.TypstBackendError, match="unknown profile"):
        tb._project_markdown(src, "does-not-exist", cfg)


def test_project_produces_projected_markdown():
    src = REPO_ROOT / "demo" / "source" / "signalling-it-refresh.md"
    cfg = REPO_ROOT / "demo" / "profiles.yaml"
    if not (src.is_file() and cfg.is_file()):
        pytest.skip("demo fixtures absent")
    internal = tb._project_markdown(src, "internal-full", cfg)
    public = tb._project_markdown(src, "public-tender", cfg)
    assert internal and public and internal != public  # projection drops blocks


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_render_project_compiles(tmp_path):
    src = REPO_ROOT / "demo" / "source" / "signalling-it-refresh.md"
    cfg = REPO_ROOT / "demo" / "profiles.yaml"
    if not (src.is_file() and cfg.is_file()):
        pytest.skip("demo fixtures absent")
    out = tb.render_pdf(src, tmp_path / "pub.pdf", project="public-tender", profiles=cfg, title="Pub")
    assert out.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_render_with_image_compiles(tmp_path):
    (tmp_path / "logo.png").write_bytes(_PNG)
    (tmp_path / "doc.md").write_text("# R\n\n![logo](logo.png)\n\nText.\n", encoding="utf-8")
    out = tb.render_pdf(tmp_path / "doc.md", tmp_path / "doc.pdf", title="R")
    assert out.read_bytes()[:5] == b"%PDF-"

@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_render_pdf_produces_valid_pdf(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text(
        "# Title\n\nA paragraph.\n\n## Table\n\n| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8")
    out = tmp_path / "doc.pdf"
    result = tb.render_pdf(md, out, title="Test", org="Org", date="2025-01-01")
    assert result == out and out.is_file()
    assert out.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_render_pdf_default_output_dir(tmp_path, monkeypatch):
    md = tmp_path / "mydoc.md"
    md.write_text("# Hi\n", encoding="utf-8")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "renders"))
    out = tb.render_pdf(md, title="Hi")
    assert out == tmp_path / "renders" / "mydoc.pdf" and out.is_file()


# --------------------------------------------------------------- dispatch --

def test_render_pdf_mode_help_routes():
    # argparse-backed: --help works with no binaries installed.
    r = subprocess.run([sys.executable, str(RENDER_PY), "pdf", "--help"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert "render pdf" in r.stdout and "--engine" in r.stdout


def test_render_pdf_mode_requires_source():
    r = subprocess.run([sys.executable, str(RENDER_PY), "pdf"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2  # argparse: missing required positional
