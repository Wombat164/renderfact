"""
Tests for D24's follow-up: the `idempotency` render-gate stage
(gates/idempotency.py + its thin wrapper in gates/run_gates.py).

Unit tests build fixture zips/PDFs directly. Integration tests drive the real
render pipeline twice via a real `render gate --stages idempotency` run
(skipped without pandoc/bash), including both a positive (PASS) and a
negative (FAIL, via a deliberately reintroduced regression) case -- a gate
that can only ever report PASS is not a verified gate.

NOTE: this branch is stacked on feat/zip-determinism (D24's own PR): the
idempotency claim this gate verifies requires that branch's SOURCE_DATE_EPOCH
export + zip_determinism.py normalization pass to already be present. Tested
against bare `main` before that branch merges, the positive-path tests below
would correctly show the gap it fixes, not a bug in this gate.
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

from gates import idempotency, run_gates  # noqa: E402

HAVE_PANDOC = shutil.which("pandoc") is not None
HAVE_PDFTOPPM = shutil.which("pdftoppm") is not None
HAVE_TYPST = shutil.which("typst") is not None


def _make_docx_zip(path: Path, members: dict[str, bytes], date_time=(2020, 1, 1, 0, 0, 0)) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=date_time)
            zf.writestr(info, data)


CORE_XML_TEMPLATE = (
    '<?xml version="1.0"?><cp:coreProperties '
    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    '<dc:identifier>renderfact:v1:{{"source_uid":"x","rendered_at":"{ts}","tool_version":"v1"}}'
    '</dc:identifier></cp:coreProperties>'
)


# ---------------------------------------------------------------- compare_docx --

def test_compare_docx_identical_is_no_diffs(tmp_path):
    a, b = tmp_path / "a.docx", tmp_path / "b.docx"
    _make_docx_zip(a, {"word/document.xml": b"<x/>"}, date_time=(2026, 1, 1, 0, 0, 0))
    _make_docx_zip(b, {"word/document.xml": b"<x/>"}, date_time=(2026, 1, 1, 0, 0, 0))
    assert idempotency.compare_docx(a, b) == []


def test_compare_docx_content_diff_is_flagged(tmp_path):
    a, b = tmp_path / "a.docx", tmp_path / "b.docx"
    _make_docx_zip(a, {"word/document.xml": b"<x/>"})
    _make_docx_zip(b, {"word/document.xml": b"<y/>"})
    diffs = idempotency.compare_docx(a, b)
    assert any("word/document.xml" in d and "content" in d for d in diffs)


def test_compare_docx_zip_timestamp_diff_is_flagged(tmp_path):
    a, b = tmp_path / "a.docx", tmp_path / "b.docx"
    _make_docx_zip(a, {"word/document.xml": b"<x/>"}, date_time=(2026, 1, 1, 0, 0, 0))
    _make_docx_zip(b, {"word/document.xml": b"<x/>"}, date_time=(2026, 1, 1, 0, 0, 5))
    diffs = idempotency.compare_docx(a, b)
    assert any("date_time" in d for d in diffs)


def test_compare_docx_missing_member_is_flagged(tmp_path):
    a, b = tmp_path / "a.docx", tmp_path / "b.docx"
    _make_docx_zip(a, {"word/document.xml": b"<x/>", "extra.xml": b"<z/>"})
    _make_docx_zip(b, {"word/document.xml": b"<x/>"})
    diffs = idempotency.compare_docx(a, b)
    assert any("member set differs" in d for d in diffs)


def test_compare_docx_rendered_at_alone_is_not_a_diff(tmp_path):
    """The one scoped exception: D11's rendered_at inside docProps/core.xml's
    provenance blob is intentionally wall-clock (D24)."""
    a, b = tmp_path / "a.docx", tmp_path / "b.docx"
    core_a = CORE_XML_TEMPLATE.format(ts="2026-07-13T10:00:00Z").encode()
    core_b = CORE_XML_TEMPLATE.format(ts="2026-07-13T10:00:05Z").encode()
    _make_docx_zip(a, {"docProps/core.xml": core_a}, date_time=(2026, 1, 1, 0, 0, 0))
    _make_docx_zip(b, {"docProps/core.xml": core_b}, date_time=(2026, 1, 1, 0, 0, 0))
    assert idempotency.compare_docx(a, b) == []


def test_compare_docx_other_core_xml_change_is_still_flagged(tmp_path):
    """rendered_at is excluded, but any OTHER core.xml difference (e.g. a
    genuine dcterms:created regression) must still surface."""
    a, b = tmp_path / "a.docx", tmp_path / "b.docx"
    core_a = CORE_XML_TEMPLATE.format(ts="2026-07-13T10:00:00Z").encode()
    core_b = core_a.replace(b'"source_uid":"x"', b'"source_uid":"DIFFERENT"')
    _make_docx_zip(a, {"docProps/core.xml": core_a}, date_time=(2026, 1, 1, 0, 0, 0))
    _make_docx_zip(b, {"docProps/core.xml": core_b}, date_time=(2026, 1, 1, 0, 0, 0))
    diffs = idempotency.compare_docx(a, b)
    assert any("docProps/core.xml" in d and "content" in d for d in diffs)


# ---------------------------------------------------------- compare_pdf_pixels --

@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PDFTOPPM), reason="needs typst + pdftoppm")
class TestComparePdfPixels:
    @staticmethod
    def _compile(tmp_path, name, body):
        typ = tmp_path / f"{name}.typ"
        typ.write_text(f'#set page(width: 10cm, height: 6cm, margin: 1cm)\n{body}\n', encoding="utf-8")
        pdf = tmp_path / f"{name}.pdf"
        subprocess.run(["typst", "compile", str(typ), str(pdf)], check=True,
                       capture_output=True, timeout=60)
        return pdf

    def test_identical_pdfs_have_no_diffs(self, tmp_path):
        a = self._compile(tmp_path, "a", "Hello World")
        b = self._compile(tmp_path, "b", "Hello World")
        diffs = idempotency.compare_pdf_pixels(a, b, tolerance=0.0, pdftoppm="pdftoppm")
        assert diffs == []

    def test_visually_different_pdfs_are_flagged(self, tmp_path):
        a = self._compile(tmp_path, "a", "Hello World")
        b = self._compile(tmp_path, "b", "#text(fill: red)[Something totally different]")
        diffs = idempotency.compare_pdf_pixels(a, b, tolerance=0.0, pdftoppm="pdftoppm")
        assert diffs != []
        assert any("pixels differ" in d for d in diffs)

    def test_tolerance_allows_a_small_difference_through(self, tmp_path):
        a = self._compile(tmp_path, "a", "Hello World")
        b = self._compile(tmp_path, "b", "#text(fill: red)[Something totally different]")
        diffs = idempotency.compare_pdf_pixels(a, b, tolerance=1.0, pdftoppm="pdftoppm")
        assert diffs == []


# ---------------------------------------------------------------------- wiring --

def test_idempotency_registered_in_stages():
    assert "idempotency" in run_gates.STAGES
    assert run_gates.STAGES["idempotency"] is run_gates.run_idempotency


def test_cli_has_idempotency_flags():
    text = (REPO_ROOT / "gates" / "run_gates.py").read_text(encoding="utf-8")
    assert "--idempotency-check-pdf" in text
    assert "--idempotency-pixel-tolerance" in text


def test_no_files_among_targets(tmp_path):
    status, detail = idempotency.check([str(tmp_path)], check_pdf=False, pixel_tolerance=0.0,
                                       which=shutil.which, runner=subprocess.run)
    assert status == "NO_FILES"


def test_check_pdf_without_pdftoppm_is_tool_missing(tmp_path):
    md = tmp_path / "d.md"
    md.write_text("# x\n", encoding="utf-8")
    status, detail = idempotency.check([str(md)], check_pdf=True, pixel_tolerance=0.0,
                                       which=lambda _name: None, runner=subprocess.run)
    assert status == "TOOL_MISSING"
    assert "pdftoppm" in detail


# ------------------------------------------------------------ integration --

def _gate_run(*extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "gates" / "run_gates.py"), *extra_args],
        capture_output=True, text=True, timeout=300,
    )


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_real_render_is_idempotent(tmp_path):
    """The positive claim: a real source, rendered twice through the real
    pipeline, passes. Requires feat/zip-determinism's fixes (this branch is
    stacked on it) -- see the module docstring."""
    src = tmp_path / "probe.md"
    src.write_text("---\ntitle: Gate Test\nversion: v1\n---\n\n# Intake\n\nPlain body.\n",
                   encoding="utf-8")
    proc = _gate_run(str(src), "--stages", "idempotency")
    combined = proc.stdout + proc.stderr
    if "bash not found" in combined or "pandoc not found" in combined:
        pytest.skip("render engines not installed on this host")
    assert proc.returncode == 0, combined
    assert "[idempotency] PASS" in combined


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_gate_fails_on_a_real_regression(tmp_path):
    """The negative claim: this gate is not vacuously green. Disabling
    ZIP_DETERMINISM_SCRIPT reintroduces the exact wall-clock zip-entry
    timestamp regression D24 fixed, and the gate must catch it."""
    src = tmp_path / "probe.md"
    src.write_text("---\ntitle: Gate Test\nversion: v1\n---\n\n# Intake\n\nPlain body.\n",
                   encoding="utf-8")
    env = {**os.environ, "ZIP_DETERMINISM_SCRIPT": ""}
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "gates" / "run_gates.py"), str(src),
         "--stages", "idempotency"],
        capture_output=True, text=True, timeout=300, env=env,
    )
    combined = proc.stdout + proc.stderr
    if "bash not found" in combined or "pandoc not found" in combined:
        pytest.skip("render engines not installed on this host")
    assert proc.returncode == 1, combined
    assert "[idempotency] FAIL" in combined
    assert "date_time differs" in combined


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_gate_never_mutates_the_real_source_file(tmp_path):
    """A gate must be read-only: running it must never persist a
    renderfact_uid (or anything else) into the real source file, only into
    the isolated scratch copy."""
    src = tmp_path / "probe.md"
    original = "---\ntitle: Gate Test\nversion: v1\n---\n\n# Intake\n\nPlain body.\n"
    src.write_text(original, encoding="utf-8")
    proc = _gate_run(str(src), "--stages", "idempotency")
    combined = proc.stdout + proc.stderr
    if "bash not found" in combined or "pandoc not found" in combined:
        pytest.skip("render engines not installed on this host")
    assert src.read_text(encoding="utf-8") == original
