"""
Tests for roundtrip/reingest.py (D11 part 3a, chunk 4.4) and the source_commit
provenance hardening (D11 part 4).

Covers: provenance verdicts (FAST_FORWARD, DIVERGED, UID mismatch, artifact
without provenance, source without a UID: all fail closed with clean messages);
extraction of Word comments and tracked changes from a hand-built minimal OOXML
zip (the extractor reads raw XML, so the fixture does not need to be a full
valid docx); structure walking and the normalized delta; the fast-forward plan
discipline (plain unique lines apply, inline-markup / duplicate / heading /
add-delete cases defer to manual); apply preserving leading list markers; the
render.py CLI end to end including the DIVERGED --apply refusal; and
source_commit (sha in a git repo, -dirty suffix, None outside a repo, and
legacy payloads without the field extracting cleanly).
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from docx import Document

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "roundtrip"))

import reingest  # noqa: E402
from roundtrip import provenance  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _make_source(tmp_path: Path, body: str = "The plan starts in March.\n") -> Path:
    src = tmp_path / "doc.md"
    src.write_text(f"---\ntitle: T\n---\n\n# Overview\n\n{body}", encoding="utf-8")
    return src


def _make_rendered_docx(tmp_path: Path, source: Path, paragraphs: list[str]) -> Path:
    doc = Document()
    doc.add_heading("Overview", level=1)
    for p in paragraphs:
        doc.add_paragraph(p)
    path = tmp_path / "rendered.docx"
    doc.save(str(path))
    provenance.embed(path, provenance.build_provenance(source))
    return path


# ---- provenance verdicts ----

def test_fast_forward_when_source_unchanged(tmp_path):
    src = _make_source(tmp_path)
    art = _make_rendered_docx(tmp_path, src, ["The plan starts in March."])
    prov, verdict = reingest.check_provenance(art, src)
    assert verdict == "FAST_FORWARD"
    assert prov.source_uid


def test_diverged_when_source_evolved(tmp_path):
    src = _make_source(tmp_path)
    art = _make_rendered_docx(tmp_path, src, ["The plan starts in March."])
    src.write_text(src.read_text(encoding="utf-8") + "\nNew paragraph.\n", encoding="utf-8")
    _prov, verdict = reingest.check_provenance(art, src)
    assert verdict == "DIVERGED"


def test_uid_mismatch_fails_closed(tmp_path):
    src_a = _make_source(tmp_path)
    art = _make_rendered_docx(tmp_path, src_a, ["x"])
    src_b = tmp_path / "other.md"
    src_b.write_text("---\ntitle: O\n---\n\nBody.\n", encoding="utf-8")
    provenance.build_provenance(src_b)  # gives other.md its own uid
    with pytest.raises(reingest.ReingestError, match="UID mismatch"):
        reingest.check_provenance(art, src_b)


def test_artifact_without_provenance_fails_closed(tmp_path):
    src = _make_source(tmp_path)
    provenance.build_provenance(src)
    doc = Document()
    doc.add_paragraph("x")
    bare = tmp_path / "bare.docx"
    doc.save(str(bare))
    with pytest.raises(reingest.ReingestError, match="no renderfact provenance"):
        reingest.check_provenance(bare, src)


def test_source_without_uid_fails_closed(tmp_path):
    src = _make_source(tmp_path)
    art = _make_rendered_docx(tmp_path, src, ["x"])
    stranger = tmp_path / "stranger.md"
    stranger.write_text("---\ntitle: S\n---\n\nBody.\n", encoding="utf-8")
    with pytest.raises(reingest.ReingestError, match="no renderfact_uid"):
        reingest.check_provenance(art, stranger)


# ---- comments + tracked changes (hand-built OOXML: the extractor reads raw XML) ----

_DOC_XML = f"""<?xml version="1.0"?>
<w:document xmlns:w="{W_NS}"><w:body>
  <w:p><w:r><w:t>Kept text.</w:t></w:r></w:p>
  <w:p><w:ins w:author="Reviewer A"><w:r><w:t>inserted words</w:t></w:r></w:ins></w:p>
  <w:p><w:del w:author="Reviewer B"><w:r><w:delText>removed words</w:delText></w:r></w:del></w:p>
</w:body></w:document>"""

_COMMENTS_XML = f"""<?xml version="1.0"?>
<w:comments xmlns:w="{W_NS}">
  <w:comment w:id="1" w:author="Reviewer A" w:date="2026-07-04T10:00:00Z">
    <w:p><w:r><w:t>Please confirm the date.</w:t></w:r></w:p>
  </w:comment>
</w:comments>"""


def _minimal_ooxml(tmp_path: Path) -> Path:
    p = tmp_path / "tracked.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", _DOC_XML)
        z.writestr("word/comments.xml", _COMMENTS_XML)
    return p


def test_extract_comments_and_tracked_changes(tmp_path):
    p = _minimal_ooxml(tmp_path)
    z = zipfile.ZipFile(p)
    comments = reingest.extract_comments(z)
    assert comments == [{"id": "1", "author": "Reviewer A",
                         "date": "2026-07-04T10:00:00Z", "text": "Please confirm the date."}]
    root = ET.fromstring(z.read("word/document.xml"))
    ins, dele = reingest.extract_tracked(root)
    assert ins == [("Reviewer A", "inserted words")]
    assert dele == [("Reviewer B", "removed words")]


def test_embedded_objects_are_inventoried_not_ignored(tmp_path):
    p = tmp_path / "with-embed.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", _DOC_XML)
        z.writestr("word/embeddings/oleObject1.xlsx", b"PK-fake-workbook-bytes")
        z.writestr("word/embeddings/blob.bin", b"\x00\x01")
    z = zipfile.ZipFile(p)
    embedded = reingest.extract_embedded(z)
    assert {e["name"] for e in embedded} == {"oleObject1.xlsx", "blob.bin"}
    xlsx = next(e for e in embedded if e["kind"] == "xlsx")
    assert xlsx["bytes"] == len(b"PK-fake-workbook-bytes")


# ---- fast-forward plan discipline ----

def _plan(md_text: str, edited_lines: list[str]):
    md_lines = [x for x in (reingest._norm(y) for y in reingest.md_plaintext(md_text)) if x]
    dx_raw = edited_lines
    dx_lines = [x for x in (reingest._norm(y) for y in dx_raw) if x]
    return reingest.plan_fast_forward(md_text, md_lines, dx_lines, dx_raw)


def test_plain_unique_rewording_is_safe():
    md = "---\ntitle: T\n---\n\n# H\n\nThe plan starts in March.\n"
    safe, manual = _plan(md, ["#> H", "The plan starts in May."])
    assert len(safe) == 1
    assert safe[0][2] == "The plan starts in May."
    assert manual == []


def test_inline_markup_line_defers_to_manual():
    md = "---\ntitle: T\n---\n\n# H\n\nThe **bold** plan starts in March.\n"
    safe, manual = _plan(md, ["#> H", "The bold plan starts in May."])
    assert safe == []
    assert any("inline markup" in (m[2] if len(m) > 2 else "") for m in manual)


def test_duplicate_normalized_line_defers_to_manual():
    md = "---\ntitle: T\n---\n\n# H\n\nSame line.\n\nOther.\n\nSame line.\n"
    safe, manual = _plan(md, ["#> H", "Same line.", "Other.", "Changed line."])
    assert safe == []
    assert manual  # ambiguity is never auto-applied


def test_heading_edits_defer_to_manual():
    md = "---\ntitle: T\n---\n\n# Old Heading\n\nBody.\n"
    safe, manual = _plan(md, ["#> New Heading", "Body."])
    assert safe == []
    assert any("heading" in (m[2] if len(m) > 2 else "") for m in manual)


def test_in_place_replacement_is_a_safe_rewording():
    """An equal-length replace opcode IS the mechanical rewording case, even when
    the whole paragraph changed: same position, plain text, unique in the source."""
    md = "---\ntitle: T\n---\n\n# H\n\nKept.\n\nDoomed.\n"
    safe, manual = _plan(md, ["#> H", "Kept.", "Brand new paragraph."])
    assert len(safe) == 1 and safe[0][2] == "Brand new paragraph."


def test_pure_additions_and_deletions_go_to_manual():
    md_add = "---\ntitle: T\n---\n\n# H\n\nKept.\n"
    safe, manual = _plan(md_add, ["#> H", "Kept.", "Brand new paragraph."])
    assert safe == []
    assert ("(added in the edited DOCX)", "Brand new paragraph.") in manual

    md_del = "---\ntitle: T\n---\n\n# H\n\nKept.\n\nDoomed.\n"
    safe, manual = _plan(md_del, ["#> H", "Kept."])
    assert safe == []
    assert ("Doomed.", "(deleted in the edited DOCX)") in manual


def test_apply_preserves_leading_list_marker(tmp_path):
    src = tmp_path / "doc.md"
    src.write_text("---\ntitle: T\n---\n\n# H\n\n- The plan starts in March.\n", encoding="utf-8")
    md_text = src.read_text(encoding="utf-8")
    safe, _ = _plan(md_text, ["#> H", "The plan starts in May."])
    assert len(safe) == 1
    reingest.apply_fast_forward(src, safe)
    assert "- The plan starts in May.\n" in src.read_text(encoding="utf-8")


# ---- CLI end to end ----

def test_cli_report_apply_and_diverged_refusal(tmp_path):
    src = _make_source(tmp_path)
    art = _make_rendered_docx(tmp_path, src, ["The plan starts in March."])
    doc = Document(str(art))
    for p in doc.paragraphs:
        if p.text == "The plan starts in March.":
            p.runs[0].text = "The plan starts in May."
    doc.save(str(art))

    report = subprocess.run(
        [sys.executable, str(RENDER_PY), "reingest", str(art), "--source", str(src), "--json"],
        capture_output=True, text=True, timeout=120,
    )
    assert report.returncode == 0, report.stderr
    payload = json.loads(report.stdout)
    assert payload["verdict"] == "FAST_FORWARD"
    assert payload["safe_edits"][0]["new"] == "The plan starts in May."
    assert payload["applied"] is None  # report-only by default

    applied = subprocess.run(
        [sys.executable, str(RENDER_PY), "reingest", str(art), "--source", str(src), "--apply"],
        capture_output=True, text=True, timeout=120,
    )
    assert applied.returncode == 0, applied.stderr
    assert "The plan starts in May." in src.read_text(encoding="utf-8")

    # the source moved past the render: DIVERGED now, and --apply must refuse
    refusal = subprocess.run(
        [sys.executable, str(RENDER_PY), "reingest", str(art), "--source", str(src), "--apply"],
        capture_output=True, text=True, timeout=120,
    )
    assert refusal.returncode == 1
    assert "DIVERGED" in refusal.stderr


# ---- source_commit hardening ----

def test_source_commit_in_a_git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"],
                   check=True, timeout=30)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True, timeout=30)
    src = _make_source(tmp_path)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, timeout=30)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "x"], check=True, timeout=30)

    commit = provenance.source_commit(src)
    assert commit and "-dirty" not in commit

    src.write_text(src.read_text(encoding="utf-8") + "\nEdit.\n", encoding="utf-8")
    assert provenance.source_commit(src).endswith("-dirty")


def test_source_commit_none_outside_git(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nonexistent-git"))
    assert provenance.source_commit(src) is None


def test_legacy_payload_without_source_commit_extracts(tmp_path):
    doc = Document()
    doc.add_paragraph("x")
    art = tmp_path / "legacy.docx"
    doc.save(str(art))
    legacy = ('renderfact:v1:{"source_uid": "abc", "source_version": "def",'
              ' "rendered_at": "2026-07-01T00:00:00Z", "tool_version": "123"}')
    d = Document(str(art))
    d.core_properties.identifier = legacy
    d.save(str(art))
    prov = provenance.extract(art)
    assert prov.source_uid == "abc"
    assert prov.source_commit is None
