"""
Tests for issue #105 (Track C10's follow-up): native markdown syntax for Word
dropdown/checkbox content controls -- docstyle/filters/form-controls.lua.

Unit tests (no binaries) cover wiring (filter ships, render-doc.sh references
FORM_CONTROLS_FILTER). Filter tests run pandoc directly and inspect the raw
docx zip (skipped without pandoc). An integration test drives the real
render-doc.sh pipeline via render.py (skipped without pandoc/bash), matching
tests/test_render_doc_toc_opt_out.py's pattern.
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

FORM_FILTER = REPO_ROOT / "docstyle" / "filters" / "form-controls.lua"
RENDER_PY = REPO_ROOT / "render.py"

HAVE_PANDOC = shutil.which("pandoc") is not None


def _pandoc_from() -> str:
    import pandoc_markdown
    return pandoc_markdown.MARKDOWN_FROM


def _md_to_docx_xml(md_text: str, tmp_path: Path, pandoc: str) -> tuple[str, subprocess.CompletedProcess]:
    """Run pandoc + the filter directly, return (document.xml text, completed process).
    document.xml is "" on a non-zero exit (caller asserts on the process instead)."""
    md = tmp_path / "d.md"
    md.write_text(md_text, encoding="utf-8")
    out = tmp_path / "d.docx"
    proc = subprocess.run(
        [pandoc, "--from", _pandoc_from(), "--lua-filter", str(FORM_FILTER), str(md), "-o", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        return "", proc
    with zipfile.ZipFile(out) as z:
        return z.read("word/document.xml").decode("utf-8"), proc


# ---------------------------------------------------------------- wiring --

def test_filter_ships():
    assert FORM_FILTER.is_file()


def test_render_doc_sh_wires_the_filter():
    text = (REPO_ROOT / "container" / "render-doc.sh").read_text(encoding="utf-8")
    assert "FORM_CONTROLS_FILTER" in text
    assert "docstyle/filters/form-controls.lua" in text


# ------------------------------------------------------- filter (pandoc) --

@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
class TestDropdown:
    def test_default_choice_is_first_when_unset(self, tmp_path):
        xml, proc = _md_to_docx_xml(
            '[ ]{.dropdown tag="dept" choices="IT|HR|Finance"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode == 0, proc.stderr
        assert "w:dropDownList" in xml
        assert '<w:listItem w:displayText="IT" w:value="IT"/>' in xml
        assert '<w:listItem w:displayText="HR" w:value="HR"/>' in xml
        assert '<w:listItem w:displayText="Finance" w:value="Finance"/>' in xml
        assert "<w:t xml:space=\"preserve\">IT</w:t>" in xml

    def test_explicit_default_is_shown(self, tmp_path):
        xml, proc = _md_to_docx_xml(
            '[ ]{.dropdown tag="dept" choices="IT|HR|Finance" default="HR"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode == 0, proc.stderr
        assert "<w:t xml:space=\"preserve\">HR</w:t>" in xml

    def test_alias_defaults_to_tag(self, tmp_path):
        xml, proc = _md_to_docx_xml(
            '[ ]{.dropdown tag="dept" choices="IT|HR"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode == 0, proc.stderr
        assert '<w:alias w:val="dept"/>' in xml
        assert '<w:tag w:val="dept"/>' in xml

    def test_explicit_alias_used(self, tmp_path):
        xml, proc = _md_to_docx_xml(
            '[ ]{.dropdown tag="dept" alias="Department" choices="IT|HR"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode == 0, proc.stderr
        assert '<w:alias w:val="Department"/>' in xml

    def test_missing_tag_fails_loudly(self, tmp_path):
        xml, proc = _md_to_docx_xml('[ ]{.dropdown choices="IT|HR"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode != 0
        assert "requires a non-empty 'tag'" in proc.stderr

    def test_missing_choices_fails_loudly(self, tmp_path):
        xml, proc = _md_to_docx_xml('[ ]{.dropdown tag="dept"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode != 0
        assert "requires a non-empty 'choices'" in proc.stderr

    def test_default_not_in_choices_fails_loudly(self, tmp_path):
        xml, proc = _md_to_docx_xml(
            '[ ]{.dropdown tag="dept" choices="IT|HR" default="Finance"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode != 0
        assert "is not one of the listed choices" in proc.stderr

    def test_choice_text_is_xml_escaped(self, tmp_path):
        xml, proc = _md_to_docx_xml(
            '[ ]{.dropdown tag="dept" choices="R&D|Legal"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode == 0, proc.stderr
        assert 'w:displayText="R&amp;D"' in xml


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
class TestCheckbox:
    def test_unchecked_by_default(self, tmp_path):
        xml, proc = _md_to_docx_xml('[ ]{.checkbox tag="agree"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode == 0, proc.stderr
        assert "w14:checkbox" in xml
        assert 'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"' in xml
        assert '<w14:checked w14:val="0"/>' in xml
        assert "☐" in xml  # BALLOT BOX

    def test_checked_true(self, tmp_path):
        xml, proc = _md_to_docx_xml('[ ]{.checkbox tag="agree" checked="true"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode == 0, proc.stderr
        assert '<w14:checked w14:val="1"/>' in xml
        assert "☒" in xml  # BALLOT BOX WITH X

    def test_missing_tag_fails_loudly(self, tmp_path):
        xml, proc = _md_to_docx_xml('[ ]{.checkbox}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode != 0
        assert "requires a non-empty 'tag'" in proc.stderr

    def test_invalid_checked_value_fails_loudly(self, tmp_path):
        xml, proc = _md_to_docx_xml('[ ]{.checkbox tag="agree" checked="yes"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode != 0
        assert 'must be "true" or "false"' in proc.stderr

    def test_local_namespace_is_self_contained(self, tmp_path):
        """The w14 namespace is declared on the w14:checkbox element itself, not
        the document root (pandoc's own default reference docx never declares
        it) -- so a checkbox works with no --reference-doc configured at all."""
        xml, proc = _md_to_docx_xml('[ ]{.checkbox tag="agree"}', tmp_path, shutil.which("pandoc"))
        assert proc.returncode == 0, proc.stderr
        root_open_tag = xml.split(">", 1)[0]
        assert "w14" not in root_open_tag


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_ids_are_deterministic_across_independent_runs(tmp_path):
    """Required for render-pipeline idempotency: the same source markdown must
    assign the same w:id sequence on every independent pandoc invocation."""
    md_text = (
        '[ ]{.dropdown tag="dept" choices="IT|HR"}\n\n'
        '[ ]{.checkbox tag="agree"}\n'
    )
    pandoc = shutil.which("pandoc")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    xml_a, proc_a = _md_to_docx_xml(md_text, tmp_path / "a", pandoc)
    xml_b, proc_b = _md_to_docx_xml(md_text, tmp_path / "b", pandoc)
    assert proc_a.returncode == 0, proc_a.stderr
    assert proc_b.returncode == 0, proc_b.stderr
    import re
    ids_a = re.findall(r'w:id w:val="(\d+)"', xml_a)
    ids_b = re.findall(r'w:id w:val="(\d+)"', xml_b)
    assert len(ids_a) == 2
    assert ids_a == ids_b


# ------------------------------------------------------------ integration --

def _render(tmp_path: Path, out_dir: str, *extra: str, env_extra: dict | None = None):
    src = tmp_path / "form-check.md"
    if not src.exists():
        src.write_text(
            "---\ntitle: Form Control Check\nversion: v1\n---\n\n"
            "# Intake\n\n"
            'Department: [ ]{.dropdown tag="dept" choices="IT|HR|Finance" default="HR"}\n\n'
            'I agree to the terms [ ]{.checkbox tag="agree"}\n',
            encoding="utf-8",
        )
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


def test_full_pipeline_renders_content_controls(tmp_path):
    src, rc, out = _render(tmp_path, "out-form-default")
    assert rc == 0, out
    docx_files = _docx_files(tmp_path, "out-form-default")
    assert len(docx_files) == 1
    with zipfile.ZipFile(docx_files[0]) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "w:dropDownList" in xml
    assert "w14:checkbox" in xml
    assert "lua-filter: form-controls.lua" in out


def test_form_controls_filter_can_be_disabled(tmp_path):
    """FORM_CONTROLS_FILTER="" is a deliberate consumer opt-out (e.g. a skin
    ships its own competing .dropdown/.checkbox handling). Pandoc's own
    behavior for an unhandled span class is a silent pass-through of its
    inline content with the class/attributes dropped -- verified directly
    against pandoc above this test file was written, not assumed -- so the
    render still succeeds (rc==0); it just does not contain content controls."""
    src, rc, out = _render(tmp_path, "out-form-disabled", env_extra={"FORM_CONTROLS_FILTER": ""})
    assert rc == 0, out
    assert "lua-filter: form-controls.lua" not in out
    docx_files = _docx_files(tmp_path, "out-form-disabled")
    assert len(docx_files) == 1
    with zipfile.ZipFile(docx_files[0]) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "w:dropDownList" not in xml
    assert "w14:checkbox" not in xml
