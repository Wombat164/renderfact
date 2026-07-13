"""
Tests for D24: zip-container timestamp/platform-metadata normalization
(docstyle/zip_determinism.py), the mechanical half of render-pipeline
idempotency.

Unit tests build fixture zips directly (no pandoc needed). An integration
test drives two independent, full `render.py docx` runs and asserts
byte-identity (skipped without pandoc/bash), the real-world claim this whole
module exists to make true.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "docstyle"))

import zip_determinism as zd  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"


def _make_zip(path: Path, members: dict[str, bytes], date_time=(2020, 1, 1, 0, 0, 0)) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=date_time)
            zf.writestr(info, data)


# ------------------------------------------------------- resolve_source_date_epoch --

def test_resolve_default_when_unset():
    assert zd.resolve_source_date_epoch({}) == zd.SOURCE_DATE_EPOCH_DEFAULT


def test_resolve_default_when_empty_string():
    assert zd.resolve_source_date_epoch({"SOURCE_DATE_EPOCH": ""}) == zd.SOURCE_DATE_EPOCH_DEFAULT


def test_resolve_uses_explicit_value():
    assert zd.resolve_source_date_epoch({"SOURCE_DATE_EPOCH": "1600000000"}) == 1600000000


# ------------------------------------------------------------------ normalize --

def test_normalize_fixes_date_time(tmp_path):
    path = tmp_path / "d.docx"
    _make_zip(path, {"a.xml": b"<a/>"}, date_time=(2026, 7, 13, 12, 0, 0))
    changed = zd.normalize(path, epoch=1700000000)
    assert changed is True
    with zipfile.ZipFile(path) as zf:
        info = zf.infolist()[0]
        assert info.date_time == zd._dos_date_time(1700000000)
        assert zf.read("a.xml") == b"<a/>"


def test_normalize_fixes_create_system_and_external_attr(tmp_path):
    path = tmp_path / "d.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("a.xml", date_time=zd._dos_date_time(1700000000))
        info.create_system = 3  # simulate a Unix-written entry
        info.external_attr = 0o755 << 16
        zf.writestr(info, b"<a/>")
    changed = zd.normalize(path, epoch=1700000000)
    assert changed is True
    with zipfile.ZipFile(path) as zf:
        info = zf.infolist()[0]
        assert info.create_system == zd.CREATE_SYSTEM
        assert info.external_attr == zd.EXTERNAL_ATTR


def test_normalize_preserves_content_and_member_order(tmp_path):
    path = tmp_path / "d.docx"
    _make_zip(path, {"z.xml": b"<z/>", "a.xml": b"<a/>", "m.xml": b"<m/>"})
    zd.normalize(path, epoch=1700000000)
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist() == ["z.xml", "a.xml", "m.xml"]
        assert zf.read("z.xml") == b"<z/>"
        assert zf.read("a.xml") == b"<a/>"
        assert zf.read("m.xml") == b"<m/>"


def test_normalize_is_a_true_noop_on_second_call(tmp_path):
    path = tmp_path / "d.docx"
    _make_zip(path, {"a.xml": b"<a/>"}, date_time=(2026, 7, 13, 12, 0, 0))
    assert zd.normalize(path, epoch=1700000000) is True
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    time.sleep(0.05)
    assert zd.normalize(path, epoch=1700000000) is False
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime  # nothing was written to disk at all


def test_normalize_already_correct_zip_is_a_noop(tmp_path):
    """A freshly built fixture's create_system/external_attr are whatever this
    platform's zipfile module defaults to, not zd.CREATE_SYSTEM/EXTERNAL_ATTR --
    so only a file already produced BY normalize() is a fair "already correct"
    input; that's exactly what test_normalize_is_a_true_noop_on_second_call
    already covers end to end. This test asserts the same claim directly
    against normalize()'s own idempotence check."""
    path = tmp_path / "d.docx"
    _make_zip(path, {"a.xml": b"<a/>"}, date_time=zd._dos_date_time(1700000000))
    zd.normalize(path, epoch=1700000000)  # first call: brings it to the normalized state
    assert zd.normalize(path, epoch=1700000000) is False


def test_normalize_two_independently_built_zips_converge_to_identical_bytes(tmp_path):
    """The actual claim this module makes: two zips built at different wall-clock
    times, on (simulated) different platforms, with identical content, become
    byte-identical after normalize()."""
    a = tmp_path / "a.docx"
    b = tmp_path / "b.docx"
    _make_zip(a, {"x.xml": b"<x/>"}, date_time=(2026, 1, 1, 0, 0, 0))
    _make_zip(b, {"x.xml": b"<x/>"}, date_time=(2026, 12, 31, 23, 59, 58))
    zd.normalize(a, epoch=1700000000)
    zd.normalize(b, epoch=1700000000)
    assert a.read_bytes() == b.read_bytes()


# ---------------------------------------------------------------------- CLI --

def test_cli_check_mode_reports_without_writing(tmp_path, capsys):
    path = tmp_path / "d.docx"
    _make_zip(path, {"a.xml": b"<a/>"}, date_time=(2026, 7, 13, 12, 0, 0))
    before = path.read_bytes()
    rc = zd.main([str(path), "--source-date-epoch", "1700000000", "--check"])
    assert rc == 1  # not yet normalized
    assert path.read_bytes() == before
    assert "would normalize" in capsys.readouterr().out


def test_cli_normalizes_and_reports(tmp_path, capsys):
    path = tmp_path / "d.docx"
    _make_zip(path, {"a.xml": b"<a/>"}, date_time=(2026, 7, 13, 12, 0, 0))
    rc = zd.main([str(path), "--source-date-epoch", "1700000000"])
    assert rc == 0
    assert "normalized" in capsys.readouterr().out
    rc2 = zd.main([str(path), "--source-date-epoch", "1700000000", "--check"])
    assert rc2 == 0
    assert "already normalized" in capsys.readouterr().out


# ------------------------------------------------------------------- wiring --

def test_render_doc_sh_wires_source_date_epoch_and_normalize():
    text = (REPO_ROOT / "container" / "render-doc.sh").read_text(encoding="utf-8")
    assert "export SOURCE_DATE_EPOCH" in text
    assert "ZIP_DETERMINISM_SCRIPT" in text
    assert "docstyle/zip_determinism.py" in text


# ------------------------------------------------------------ integration --

HAVE_PANDOC = (__import__("shutil").which("pandoc") is not None)


def _render(tmp_path: Path, out_dir: str, env_extra: dict | None = None):
    src = tmp_path / "determinism-check.md"
    if not src.exists():
        src.write_text(
            "---\ntitle: Determinism Integration Check\nversion: v1\n---\n\n"
            "# Intake\n\nPlain body text.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n",
            encoding="utf-8",
        )
    env = {**os.environ, "OUTPUT_DIR": str(tmp_path / out_dir), **(env_extra or {})}
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "docx", str(src)],
        capture_output=True, text=True, timeout=180, env=env, cwd=tmp_path,
    )
    combined = result.stdout + result.stderr
    if result.returncode == 3 and ("pandoc not found" in combined or "bash not found" in combined):
        pytest.skip("render engines not installed on this host: " + combined.strip()[:120])
    return src, result.returncode, combined


def _docx_files(tmp_path: Path, out_dir: str) -> list[Path]:
    return sorted((tmp_path / out_dir).glob("*.docx"))


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_two_independent_renders_are_byte_identical_with_provenance_off(tmp_path):
    _render(tmp_path, "out-a", env_extra={"PROVENANCE": "off"})
    time.sleep(1.5)
    _render(tmp_path, "out-b", env_extra={"PROVENANCE": "off"})
    a = _docx_files(tmp_path, "out-a")
    b = _docx_files(tmp_path, "out-b")
    assert len(a) == 1 and len(b) == 1
    assert a[0].read_bytes() == b[0].read_bytes()


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_two_independent_renders_with_provenance_differ_only_in_core_xml(tmp_path):
    """PROVENANCE=auto (default): the ONE expected difference is docProps/core.xml
    (carries the intentionally-wall-clock rendered_at field, D11/D24) -- not zip
    entry timestamps, not any other member's content. Uses a stable, pre-seeded
    source so the renderfact_uid first-render source mutation (source_uid.py)
    isn't itself a confound."""
    src = tmp_path / "determinism-check.md"
    src.write_text(
        "---\ntitle: Determinism Integration Check\nversion: v1\n---\n\n"
        "# Intake\n\nPlain body text.\n",
        encoding="utf-8",
    )
    _render(tmp_path, "out-seed")  # establishes renderfact_uid in src's frontmatter
    _render(tmp_path, "out-e")
    time.sleep(1.5)
    _render(tmp_path, "out-f")
    e = _docx_files(tmp_path, "out-e")[0]
    f = _docx_files(tmp_path, "out-f")[0]
    with zipfile.ZipFile(e) as ze, zipfile.ZipFile(f) as zf:
        diffs = [n for n in ze.namelist() if ze.read(n) != zf.read(n)]
        for ie, iff in zip(ze.infolist(), zf.infolist()):
            assert ie.date_time == iff.date_time, f"zip-entry timestamp cruft leaked: {ie.filename}"
    assert diffs == ["docProps/core.xml"]
