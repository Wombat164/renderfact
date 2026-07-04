"""
Tests for docstyle/ooxml_theme.py + docstyle/template_import.py (chunk C7a: DOCX
template import, style axis).

All DOCX fixtures are built in tmp_path via python-docx, then a KNOWN DrawingML
theme is injected by rewriting word/theme/theme1.xml inside the zip directly
(python-docx has no theme-writing API; this mirrors how docstyle/
heading_numbering.py's own tests rewrite a docx zip in place). Covers: theme
resolution (srgbClr AND sysClr/lastClr), ThemeError on a package with no theme
part, the derived profile's provenance header + only-derivable-keys-uncommented
shape, section geometry mapping, the --check comparison function in isolation,
one real --check integration test through render-doc.sh (skipif pandoc/bash
absent), and one real subprocess dispatch test through render.py.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Cm, Pt, RGBColor

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "docstyle"))

from docstyle import template_import as ti  # noqa: E402
from docstyle.ooxml_theme import Theme, ThemeError, read_theme  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"

KNOWN_ACCENT1 = "FF6600"
KNOWN_DK1 = "222222"  # via sysClr lastClr
KNOWN_MAJOR_FONT = "Georgia"
KNOWN_MINOR_FONT = "Verdana"

_THEME_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Test Theme">
  <a:themeElements>
    <a:clrScheme name="Test">
      <a:dk1><a:sysClr val="windowText" lastClr="{KNOWN_DK1}"/></a:dk1>
      <a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="1F1F1F"/></a:dk2>
      <a:lt2><a:srgbClr val="EEEEEE"/></a:lt2>
      <a:accent1><a:srgbClr val="{KNOWN_ACCENT1}"/></a:accent1>
      <a:accent2><a:srgbClr val="336699"/></a:accent2>
      <a:accent3><a:srgbClr val="669933"/></a:accent3>
      <a:accent4><a:srgbClr val="993366"/></a:accent4>
      <a:accent5><a:srgbClr val="999933"/></a:accent5>
      <a:accent6><a:srgbClr val="336633"/></a:accent6>
      <a:hlink><a:srgbClr val="0563C1"/></a:hlink>
      <a:folHlink><a:srgbClr val="954F72"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Test">
      <a:majorFont><a:latin typeface="{KNOWN_MAJOR_FONT}"/></a:majorFont>
      <a:minorFont><a:latin typeface="{KNOWN_MINOR_FONT}"/></a:minorFont>
    </a:fontScheme>
  </a:themeElements>
</a:theme>"""


def _rewrite_zip_entry(docx_path: Path, entry: str, data: bytes | None) -> None:
    """Rewrite one zip entry's content (data=None deletes the entry). Mirrors
    docstyle/heading_numbering.process()'s own in-place zip rewrite pattern."""
    with zipfile.ZipFile(docx_path) as zin:
        items = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    if data is None:
        items.pop(entry, None)
    else:
        items[entry] = data
    with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in items.items():
            zout.writestr(name, blob)


def _build_branded_template(tmp_path, name="corporate.docx") -> Path:
    """A synthetic 'corporate template': python-docx styles (Normal font/colour,
    Heading 1 colour) + explicit section geometry, with a KNOWN theme injected
    (accent1 srgbClr, dk1 sysClr/lastClr, known major/minor fonts)."""
    path = tmp_path / name
    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(2.0)
    sec.right_margin = Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = KNOWN_MINOR_FONT
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor(0x22, 0x22, 0x22)

    h1 = doc.styles["Heading 1"]
    h1.font.color.rgb = RGBColor(0xFF, 0x66, 0x00)

    doc.add_heading("Corporate Title", level=1)
    doc.add_paragraph("Body paragraph text for the corporate template test fixture.")
    doc.save(str(path))

    _rewrite_zip_entry(path, "word/theme/theme1.xml", _THEME_XML.encode("utf-8"))
    return path


def _template_with_no_theme(tmp_path, name="no-theme.docx") -> Path:
    doc = Document()
    doc.add_paragraph("no theme here")
    path = tmp_path / name
    doc.save(str(path))
    _rewrite_zip_entry(path, "word/theme/theme1.xml", None)
    return path


# ---------- (a) ooxml_theme.py: theme resolution incl. sysClr/lastClr ----------

def test_read_theme_resolves_srgb_and_sysclr(tmp_path):
    template = _build_branded_template(tmp_path)
    theme = read_theme(template)
    assert isinstance(theme, Theme)
    assert theme.colors["accent1"] == KNOWN_ACCENT1     # srgbClr
    assert theme.colors["dk1"] == KNOWN_DK1              # sysClr/lastClr
    assert theme.colors["lt1"] == "FFFFFF"               # sysClr/lastClr, second role
    assert theme.fonts["major"] == KNOWN_MAJOR_FONT
    assert theme.fonts["minor"] == KNOWN_MINOR_FONT


def test_read_theme_raises_on_missing_theme_part(tmp_path):
    path = _template_with_no_theme(tmp_path)
    with pytest.raises(ThemeError):
        read_theme(path)


def test_read_theme_raises_on_non_ooxml_zip(tmp_path):
    path = tmp_path / "not-office.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("hello.txt", "not an office package")
    with pytest.raises(ThemeError):
        read_theme(path)


# ---------- (b) derived profile: injected values + provenance + only-derivable-uncommented ----------

def test_derive_profile_and_yaml_carry_injected_values(tmp_path):
    template = _build_branded_template(tmp_path)
    theme = read_theme(template)
    doc = Document(str(template))
    dp = ti.derive_profile(doc, theme)

    assert dp.derived["accent"] == KNOWN_ACCENT1
    assert dp.derived["body"] == "222222"
    assert dp.derived["font"] == KNOWN_MINOR_FONT
    assert dp.derived["page_width_cm"] == 21.0
    assert dp.derived["page_height_cm"] == 29.7
    assert dp.derived["margin_cm"] == 2.0
    # never derivable from a DOCX template in v1 scope
    assert set(dp.not_derived) >= {"body_muted", "table_body", "zebra"}

    prov = ti.build_import_provenance(template, date_str="2026-07-03")
    yaml_text = ti.render_profile_yaml(prov, dp)

    assert f"source template: {template.name}" in yaml_text
    m = re.search(r"source sha256:\s+([0-9a-f]{64})", yaml_text)
    assert m, yaml_text
    assert "import date:     2026-07-03" in yaml_text
    assert "tool_version:" in yaml_text

    # derivable keys present UNCOMMENTED as real yaml assignments
    assert f'accent: "{KNOWN_ACCENT1}"' in yaml_text
    assert f"font: {KNOWN_MINOR_FONT}" in yaml_text
    assert "page_width_cm: 21.0" in yaml_text
    assert "margin_cm: 2.0" in yaml_text
    # never a bare (uncommented) line for the never-derivable keys
    for key in ("body_muted", "table_body", "zebra"):
        assert re.search(rf"^{key}:", yaml_text, re.MULTILINE) is None
        assert re.search(rf"^# {key}: not derivable", yaml_text, re.MULTILINE) is not None


def test_derive_profile_falls_back_to_theme_when_style_unset(tmp_path):
    # Normal/Heading 1 carry NO explicit colour/font -> theme accent1/dk1/minor used.
    path = tmp_path / "theme-only.docx"
    doc = Document()
    doc.add_heading("Heading with no explicit colour", level=1)
    doc.add_paragraph("Body with no explicit colour or font.")
    doc.save(str(path))
    _rewrite_zip_entry(path, "word/theme/theme1.xml", _THEME_XML.encode("utf-8"))

    theme = read_theme(path)
    doc2 = Document(str(path))
    dp = ti.derive_profile(doc2, theme)
    assert dp.derived["accent"] == KNOWN_ACCENT1
    assert dp.derived["body"] == KNOWN_DK1
    assert dp.derived["font"] == KNOWN_MINOR_FONT


def test_main_writes_profile_with_copy_reference(tmp_path):
    template = _build_branded_template(tmp_path)
    out_dir = tmp_path / "skin"
    rc = ti.main([str(template), "--out-dir", str(out_dir), "--copy-reference",
                  "--date", "2026-07-03"])
    assert rc == 0
    profile_path = out_dir / "template-profile.yaml"
    assert profile_path.exists()
    assert (out_dir / "reference.docx").exists()
    text = profile_path.read_text(encoding="utf-8")
    assert f'accent: "{KNOWN_ACCENT1}"' in text


# ---------- (c) section geometry mapping ----------

def test_section_geometry_uniform_margin(tmp_path):
    template = _build_branded_template(tmp_path)
    doc = Document(str(template))
    geom = ti.section_geometry_cm(doc.sections[0])
    assert geom["page_width_cm"] == 21.0
    assert geom["page_height_cm"] == 29.7
    assert geom["margin_cm"] == 2.0


def test_section_geometry_asymmetric_margin_not_derived(tmp_path):
    path = tmp_path / "asym.docx"
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(3.0)   # deliberately different
    sec.right_margin = Cm(2.0)
    doc.add_paragraph("body")
    doc.save(str(path))

    theme = Theme(colors={}, fonts={})
    doc2 = Document(str(path))
    dp = ti.derive_profile(doc2, theme)
    assert "margin_cm" not in dp.derived
    assert "margin_cm" in dp.not_derived
    assert "not uniform" in dp.not_derived["margin_cm"]


# ---------- (d) --check comparison function, unit-tested directly ----------

def test_compare_properties_pass_and_drift():
    expected = {"font": "Arial", "accent": "1F3864", "body": "262626",
               "page_width_cm": 21.0, "page_height_cm": 29.7, "margin_cm": 2.0}
    actual_matching = dict(expected)
    rows = ti.compare_properties(expected, actual_matching)
    assert all(r.status == "PASS" for r in rows)
    assert {r.key for r in rows} == set(expected)

    actual_drifted = dict(expected)
    actual_drifted["accent"] = "000000"
    actual_drifted["page_width_cm"] = 25.0
    rows2 = ti.compare_properties(expected, actual_drifted)
    by_key = {r.key: r.status for r in rows2}
    assert by_key["accent"] == "DRIFT"
    assert by_key["page_width_cm"] == "DRIFT"
    assert by_key["font"] == "PASS"
    assert by_key["body"] == "PASS"


def test_compare_properties_skips_non_derivable_expected():
    expected = {"font": "Arial", "accent": None}  # accent not derivable from the template
    actual = {"font": "Arial", "accent": "ANYTHING"}
    rows = ti.compare_properties(expected, actual)
    by_key = {r.key: r.status for r in rows}
    assert by_key["accent"] == "SKIP"
    assert by_key["font"] == "PASS"


def test_format_comparison_table_reads_cleanly():
    rows = ti.compare_properties(
        {"font": "Arial", "accent": None},
        {"font": "Arial", "accent": "X"},
    )
    table = ti.format_comparison_table(rows)
    assert "font" in table and "PASS" in table
    assert "(not derivable)" in table and "SKIP" in table


# ---------- (e) real --check integration through render-doc.sh ----------

_PANDOC_AND_BASH_AVAILABLE = shutil.which("pandoc") is not None and shutil.which("bash") is not None


@pytest.mark.skipif(not _PANDOC_AND_BASH_AVAILABLE, reason="requires pandoc and bash on PATH")
def test_check_gate_clean_render_through_real_pipeline(tmp_path, capsys):
    template = _build_branded_template(tmp_path)
    probe = tmp_path / "probe.md"
    probe.write_text(
        "---\n"
        "title: Probe Document\n"
        "version: v1\n"
        "---\n\n"
        "# Part I: Probe Heading\n\n"
        "This is a probe body paragraph long enough to exercise the justify/style "
        "rules the same way a real document's body text would.\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "skin"
    rc = ti.main([str(template), "--out-dir", str(out_dir), "--check", str(probe)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PASS" in out
    assert "DRIFT" not in out


# ---------- (f) real subprocess dispatch through render.py ----------

def test_render_py_dispatches_import_template(tmp_path):
    template = _build_branded_template(tmp_path)
    out_dir = tmp_path / "skin"
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "import-template", str(template),
         "--out-dir", str(out_dir), "--date", "2026-07-03"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    profile_path = out_dir / "template-profile.yaml"
    assert profile_path.exists()
    text = profile_path.read_text(encoding="utf-8")
    assert f'accent: "{KNOWN_ACCENT1}"' in text
    assert "TEMPLATE_DOCX=" in result.stdout
    assert "TEMPLATE_PROFILE=" in result.stdout
