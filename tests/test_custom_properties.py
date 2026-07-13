"""
Tests for issue #105's sibling feature: custom document properties
(docProps/custom.xml) + DOCPROPERTY field references.

Unit tests exercise docstyle/custom_properties.py directly (no pandoc needed).
Filter tests run pandoc + docstyle/filters/doc-properties.lua and inspect the
raw docx zip (skipped without pandoc). An integration test drives the real
render-doc.sh pipeline via render.py (skipped without pandoc/bash).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "docstyle"))

import custom_properties as cp  # noqa: E402
import pandoc_markdown  # noqa: E402

DOC_PROP_FILTER = REPO_ROOT / "docstyle" / "filters" / "doc-properties.lua"
RENDER_PY = REPO_ROOT / "render.py"

HAVE_PANDOC = shutil.which("pandoc") is not None


# ---------------------------------------------------------------- wiring --

def test_filter_ships():
    assert DOC_PROP_FILTER.is_file()


def test_render_doc_sh_wires_both_pieces():
    text = (REPO_ROOT / "container" / "render-doc.sh").read_text(encoding="utf-8")
    assert "DOC_PROPERTIES_FILTER" in text
    assert "docstyle/filters/doc-properties.lua" in text
    assert "CUSTOM_PROPERTIES_SCRIPT" in text
    assert "docstyle/custom_properties.py" in text


# ---------------------------------------------------- load_custom_properties --

def test_load_custom_properties_no_profile_is_empty():
    assert cp.load_custom_properties(None) == {}


def test_load_custom_properties_missing_file_is_empty(tmp_path):
    assert cp.load_custom_properties(tmp_path / "nope.yaml") == {}


def test_load_custom_properties_no_key_is_empty(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text("font: Arial\n", encoding="utf-8")
    assert cp.load_custom_properties(p) == {}


def test_load_custom_properties_parses_all_types(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(
        "custom_properties:\n"
        "  ClientName: {type: text, value: Acme}\n"
        "  Budget: {type: number, value: 50000}\n"
        "  IsConfidential: {type: bool, value: true}\n"
        "  ApprovedOn: {type: date, value: '2026-07-13'}\n",
        encoding="utf-8",
    )
    props = cp.load_custom_properties(p)
    assert props == {
        "ClientName": {"type": "text", "value": "Acme"},
        "Budget": {"type": "number", "value": 50000},
        "IsConfidential": {"type": "bool", "value": True},
        "ApprovedOn": {"type": "date", "value": "2026-07-13"},
    }


def test_load_custom_properties_default_type_is_text(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text("custom_properties:\n  Foo: {value: bar}\n", encoding="utf-8")
    assert cp.load_custom_properties(p)["Foo"]["type"] == "text"


def test_load_custom_properties_rejects_bad_name(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text("custom_properties:\n  'bad name!': {value: x}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="alphanumeric"):
        cp.load_custom_properties(p)


def test_load_custom_properties_rejects_bad_type(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text("custom_properties:\n  Foo: {type: currency, value: 5}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="type"):
        cp.load_custom_properties(p)


# --------------------------------------------------------------- _vt_element --

def test_vt_element_text():
    assert cp._vt_element("text", "hello") == ("lpwstr", "hello")


def test_vt_element_bool_true():
    assert cp._vt_element("bool", True) == ("bool", "1")


def test_vt_element_bool_false():
    assert cp._vt_element("bool", False) == ("bool", "0")


def test_vt_element_number_integer_uses_i4():
    assert cp._vt_element("number", 50000) == ("i4", "50000")


def test_vt_element_number_fraction_uses_r8():
    assert cp._vt_element("number", 12.5) == ("r8", "12.5")


def test_vt_element_date_bare_date_gets_time_and_z():
    assert cp._vt_element("date", "2026-07-13") == ("filetime", "2026-07-13T00:00:00Z")


def test_vt_element_date_rejects_malformed():
    with pytest.raises(ValueError):
        cp._vt_element("date", "not-a-date")


# ------------------------------------------------------------- _merge_custom_xml --

def test_merge_into_fresh_part_assigns_pid_starting_at_2():
    xml_bytes, changed = cp._merge_custom_xml(None, {"Foo": {"type": "text", "value": "bar"}})
    assert changed == 1
    assert b'pid="2"' in xml_bytes
    assert b'name="Foo"' in xml_bytes


def test_merge_preserves_foreign_property_untouched():
    existing = cp._MINIMAL_CUSTOM_XML.encode("utf-8").replace(
        b"/>", b'><property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" '
               b'name="version"><vt:lpwstr>v1</vt:lpwstr></property></Properties>'
    )
    xml_bytes, changed = cp._merge_custom_xml(existing, {"ClientName": {"type": "text", "value": "Acme"}})
    assert changed == 1
    assert b'name="version"' in xml_bytes and b'pid="2"' in xml_bytes  # untouched
    assert b'name="ClientName"' in xml_bytes and b'pid="3"' in xml_bytes  # appended after


def test_merge_updates_existing_value_same_pid():
    xml1, _ = cp._merge_custom_xml(None, {"Foo": {"type": "text", "value": "old"}})
    xml2, changed = cp._merge_custom_xml(xml1, {"Foo": {"type": "text", "value": "new"}})
    assert changed == 1
    assert b'pid="2"' in xml2  # same pid, not reassigned
    assert b"new" in xml2 and b"old" not in xml2


def test_merge_already_correct_value_is_a_true_noop():
    xml1, _ = cp._merge_custom_xml(None, {"Foo": {"type": "text", "value": "bar"}})
    xml2, changed = cp._merge_custom_xml(xml1, {"Foo": {"type": "text", "value": "bar"}})
    assert changed == 0
    assert xml1 == xml2


# ---------------------------------------------------------- _fill_docproperty_fields --

def test_fill_replaces_placeholder_with_real_value():
    doc_xml = '<w:fldSimple w:instr=" DOCPROPERTY Foo \\* MERGEFORMAT "><w:r><w:t>«Foo»</w:t></w:r></w:fldSimple>'
    new_xml, unbound = cp._fill_docproperty_fields(doc_xml, {"Foo": {"type": "text", "value": "bar"}})
    assert "<w:t>bar</w:t>" in new_xml
    assert unbound == []


def test_fill_leaves_unbound_field_untouched_and_reports_it():
    doc_xml = '<w:fldSimple w:instr=" DOCPROPERTY Ghost \\* MERGEFORMAT "><w:r><w:t>«Ghost»</w:t></w:r></w:fldSimple>'
    new_xml, unbound = cp._fill_docproperty_fields(doc_xml, {})
    assert new_xml == doc_xml
    assert unbound == ["Ghost"]


def test_fill_escapes_xml_special_characters():
    doc_xml = '<w:fldSimple w:instr=" DOCPROPERTY Foo \\* MERGEFORMAT "><w:r><w:t>«Foo»</w:t></w:r></w:fldSimple>'
    new_xml, _ = cp._fill_docproperty_fields(doc_xml, {"Foo": {"type": "text", "value": "R&D <legal>"}})
    assert "R&amp;D &lt;legal&gt;" in new_xml


# --------------------------------------------------------------------- process --

def _minimal_docx(tmp_path: Path, with_field_for: str | None = None) -> Path:
    """A minimal but real docx with (optionally) one DOCPROPERTY fldSimple,
    built the same way docstyle/filters/doc-properties.lua would emit it --
    a CONTRIBUTING.md-style programmatic fixture, not a binary blob."""
    import docx
    from docx.oxml.ns import qn
    from lxml import etree

    doc = docx.Document()
    p = doc.add_paragraph("Client: ")
    if with_field_for:
        fld = etree.SubElement(p._p, qn("w:fldSimple"))
        fld.set(qn("w:instr"), f" DOCPROPERTY {with_field_for} \\* MERGEFORMAT ")
        r = etree.SubElement(fld, qn("w:r"))
        t = etree.SubElement(r, qn("w:t"))
        t.text = f"«{with_field_for}»"
    path = tmp_path / "d.docx"
    doc.save(str(path))
    return path


def test_process_no_properties_is_a_noop(tmp_path):
    path = _minimal_docx(tmp_path)
    assert cp.process(path, {}) == 0


def test_process_writes_custom_xml_and_fills_field(tmp_path):
    path = _minimal_docx(tmp_path, with_field_for="ClientName")
    n = cp.process(path, {"ClientName": {"type": "text", "value": "Acme Corp"}})
    assert n == 1
    with zipfile.ZipFile(path) as z:
        assert "docProps/custom.xml" in z.namelist()
        custom_xml = z.read("docProps/custom.xml").decode("utf-8")
        assert "Acme Corp" in custom_xml
        doc_xml = z.read("word/document.xml").decode("utf-8")
        assert "<w:t>Acme Corp</w:t>" in doc_xml


def test_process_is_idempotent_second_run_is_byte_identical(tmp_path):
    path = _minimal_docx(tmp_path, with_field_for="ClientName")
    props = {"ClientName": {"type": "text", "value": "Acme Corp"}}
    assert cp.process(path, props) == 1
    before = path.read_bytes()
    assert cp.process(path, props) == 0
    assert path.read_bytes() == before


def test_process_check_mode_writes_nothing(tmp_path):
    path = _minimal_docx(tmp_path, with_field_for="ClientName")
    before = path.read_bytes()
    n = cp.process(path, {"ClientName": {"type": "text", "value": "Acme Corp"}}, check=True)
    assert n != 0
    assert path.read_bytes() == before


def test_process_warns_on_unbound_field(tmp_path, capsys):
    path = _minimal_docx(tmp_path, with_field_for="Ghost")
    cp.process(path, {"Other": {"type": "text", "value": "x"}})
    captured = capsys.readouterr()
    assert "Ghost" in captured.err


def test_process_merges_with_existing_foreign_property(tmp_path):
    """The exact scenario discovered empirically: pandoc itself writes a
    docProps/custom.xml `version` property from YAML frontmatter's `version:`
    key. process() must never clobber it."""
    path = _minimal_docx(tmp_path, with_field_for="ClientName")
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    members["docProps/custom.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="version">'
        '<vt:lpwstr>v1</vt:lpwstr></property></Properties>'
    ).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in members.items():
            z.writestr(n, d)

    cp.process(path, {"ClientName": {"type": "text", "value": "Acme Corp"}})
    with zipfile.ZipFile(path) as z:
        custom_xml = z.read("docProps/custom.xml").decode("utf-8")
    assert 'name="version"' in custom_xml and 'pid="2"' in custom_xml
    assert 'name="ClientName"' in custom_xml and 'pid="3"' in custom_xml


# ------------------------------------------------------- filter (pandoc) --

@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_filter_emits_fldsimple_with_placeholder(tmp_path):
    md = tmp_path / "d.md"
    md.write_text('Client: [ ]{.docproperty name="ClientName"}\n', encoding="utf-8")
    out = tmp_path / "d.docx"
    proc = subprocess.run(
        ["pandoc", "--from", pandoc_markdown.MARKDOWN_FROM,
         "--lua-filter", str(DOC_PROP_FILTER), str(md), "-o", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert 'DOCPROPERTY ClientName' in xml
    assert "«ClientName»" in xml


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_filter_missing_name_fails_loudly(tmp_path):
    md = tmp_path / "d.md"
    md.write_text('[ ]{.docproperty}\n', encoding="utf-8")
    out = tmp_path / "d.docx"
    proc = subprocess.run(
        ["pandoc", "--from", pandoc_markdown.MARKDOWN_FROM,
         "--lua-filter", str(DOC_PROP_FILTER), str(md), "-o", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert "requires a non-empty 'name'" in proc.stderr


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_filter_rejects_non_alnum_name(tmp_path):
    md = tmp_path / "d.md"
    md.write_text('[ ]{.docproperty name="bad name"}\n', encoding="utf-8")
    out = tmp_path / "d.docx"
    proc = subprocess.run(
        ["pandoc", "--from", pandoc_markdown.MARKDOWN_FROM,
         "--lua-filter", str(DOC_PROP_FILTER), str(md), "-o", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert "alphanumeric" in proc.stderr


# ------------------------------------------------------------ integration --

def _render(tmp_path: Path, out_dir: str, *extra: str, env_extra: dict | None = None):
    src = tmp_path / "custom-props-check.md"
    if not src.exists():
        src.write_text(
            "---\ntitle: Custom Props Check\nversion: v1\n---\n\n"
            "# Intake\n\n"
            'Client: [ ]{.docproperty name="ClientName"}\n\n'
            'Budget: [ ]{.docproperty name="Budget"}\n',
            encoding="utf-8",
        )
    profile = tmp_path / "profile.yaml"
    if not profile.exists():
        profile.write_text(
            "custom_properties:\n"
            "  ClientName: {type: text, value: 'Acme Corp'}\n"
            "  Budget: {type: number, value: 50000}\n",
            encoding="utf-8",
        )
    env = {**os.environ, "OUTPUT_DIR": str(tmp_path / out_dir),
           "TEMPLATE_PROFILE": str(profile), **(env_extra or {})}
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


def test_full_pipeline_writes_custom_properties_and_fills_fields(tmp_path):
    src, rc, out = _render(tmp_path, "out-custom-props")
    assert rc == 0, out
    docx_files = _docx_files(tmp_path, "out-custom-props")
    assert len(docx_files) == 1
    with zipfile.ZipFile(docx_files[0]) as z:
        custom_xml = z.read("docProps/custom.xml").decode("utf-8")
        doc_xml = z.read("word/document.xml").decode("utf-8")
    assert "Acme Corp" in custom_xml
    assert "50000" in custom_xml
    assert "<w:t>Acme Corp</w:t>" in doc_xml
    assert "updated 2 custom properties" in out


def test_full_pipeline_skips_cleanly_without_template_profile(tmp_path):
    src = tmp_path / "no-profile.md"
    src.write_text("---\ntitle: No Profile\nversion: v1\n---\n\n# Heading\n\nplain text\n", encoding="utf-8")
    env = {**os.environ, "OUTPUT_DIR": str(tmp_path / "out-no-profile"), "TEMPLATE_PROFILE": ""}
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "docx", str(src)],
        capture_output=True, text=True, timeout=180, env=env, cwd=tmp_path,
    )
    combined = result.stdout + result.stderr
    if result.returncode == 3 and ("pandoc not found" in combined or "bash not found" in combined):
        pytest.skip("render engines not installed on this host")
    assert result.returncode == 0, combined
    assert "Skipping custom document properties" in combined
