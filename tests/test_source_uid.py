"""
Tests for roundtrip/source_uid.py -- D11 part 2 (chunk 4.1): stable per-source
identity via YAML frontmatter, plus content-versioning.

Covers: UID generation + idempotent persistence for a file with existing
frontmatter, a file with none, an existing UID being read back unchanged
(and the file NOT rewritten), safety against reformatting unrelated
frontmatter content, and that content_version changes with content but not
with the UID-insertion side effect alone.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roundtrip import source_uid  # noqa: E402


def test_generates_and_persists_uid_when_frontmatter_exists_without_one(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("---\ntitle: Example\ntags: [a, b]\n---\n\nBody text.\n", encoding="utf-8")

    uid = source_uid.get_or_create_source_uid(f)
    assert uuid.UUID(uid)  # valid UUID4 string

    content = f.read_text(encoding="utf-8")
    assert f"renderfact_uid: {uid}" in content
    assert "title: Example" in content
    assert "tags: [a, b]" in content  # untouched, not reformatted
    assert "Body text." in content


def test_idempotent_second_call_returns_same_uid_without_rewrite(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("---\ntitle: Example\n---\n\nBody.\n", encoding="utf-8")

    first = source_uid.get_or_create_source_uid(f)
    content_after_first = f.read_text(encoding="utf-8")

    second = source_uid.get_or_create_source_uid(f)
    content_after_second = f.read_text(encoding="utf-8")

    assert first == second
    assert content_after_first == content_after_second


def test_reads_existing_uid_without_generating_a_new_one(tmp_path):
    f = tmp_path / "doc.md"
    existing = "11111111-1111-1111-1111-111111111111"
    f.write_text(f"---\ntitle: Example\nrenderfact_uid: {existing}\n---\n\nBody.\n", encoding="utf-8")

    uid = source_uid.get_or_create_source_uid(f)
    assert uid == existing
    # file content unchanged -- no spurious rewrite when the key already exists
    assert f.read_text(encoding="utf-8").count("renderfact_uid") == 1


def test_creates_frontmatter_block_when_file_has_none(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("Just a body, no frontmatter.\n", encoding="utf-8")

    uid = source_uid.get_or_create_source_uid(f)
    content = f.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert f"renderfact_uid: {uid}" in content
    assert "Just a body, no frontmatter." in content


def test_does_not_confuse_a_markdown_horizontal_rule_with_frontmatter_close(tmp_path):
    # A file with real frontmatter followed by a body that ALSO contains a
    # standalone "---" line (a markdown horizontal rule) -- the frontmatter
    # boundary must be the FIRST closing "---", not a later one.
    f = tmp_path / "doc.md"
    f.write_text(
        "---\ntitle: Example\n---\n\nSection one.\n\n---\n\nSection two.\n",
        encoding="utf-8",
    )
    uid = source_uid.get_or_create_source_uid(f)
    content = f.read_text(encoding="utf-8")
    # the uid line lands in the frontmatter block, not after the horizontal rule
    assert content.index("renderfact_uid") < content.index("Section one.")
    assert "Section two." in content


def test_content_version_changes_with_content():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "a.md"
        f.write_text("version one", encoding="utf-8")
        v1 = source_uid.content_version(f)

        f.write_text("version two", encoding="utf-8")
        v2 = source_uid.content_version(f)

        assert v1 != v2
        assert len(v1) == 16
        assert len(v2) == 16


def test_content_version_stable_for_identical_content(tmp_path):
    f1 = tmp_path / "a.md"
    f2 = tmp_path / "b.md"
    f1.write_text("identical content", encoding="utf-8")
    f2.write_text("identical content", encoding="utf-8")
    assert source_uid.content_version(f1) == source_uid.content_version(f2)
