"""
Tests for roundtrip/dossier_role.py -- issue #77: the read-only `dossier_role`
frontmatter accessor.

Covers: reading a set value, absence (no key, no frontmatter at all, empty
frontmatter), a whitespace-only value treated as unset, freeform values (no
enum -- any string round-trips), coexistence with other frontmatter keys
(renderfact_uid included, since a real source often carries both), and that
reading never mutates the file (contrast source_uid.get_or_create_source_uid,
which persists a generated value -- dossier_role is always author-stated).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roundtrip import dossier_role  # noqa: E402


def test_reads_a_set_dossier_role(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text(
        "---\ntitle: Onboarding overview\ndossier_role: the single-page entry point; "
        "every other document in this dossier goes deeper on one facet\n---\n\nBody.\n",
        encoding="utf-8",
    )
    assert dossier_role.read_dossier_role(f) == (
        "the single-page entry point; every other document in this dossier goes deeper on one facet"
    )


def test_returns_none_when_key_absent(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("---\ntitle: Example\n---\n\nBody.\n", encoding="utf-8")
    assert dossier_role.read_dossier_role(f) is None


def test_returns_none_when_no_frontmatter_at_all(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("Just a body, no frontmatter.\n", encoding="utf-8")
    assert dossier_role.read_dossier_role(f) is None


def test_returns_none_for_empty_frontmatter_block(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("---\n---\n\nBody.\n", encoding="utf-8")
    assert dossier_role.read_dossier_role(f) is None


def test_whitespace_only_value_treated_as_unset(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text('---\ndossier_role: "   "\n---\n\nBody.\n', encoding="utf-8")
    assert dossier_role.read_dossier_role(f) is None


def test_freeform_value_is_returned_verbatim_no_enum_check(tmp_path):
    # Consumer-defined vocabulary: any string is accepted, unlike a clearance/
    # distribution ladder value, which would raise ProjectionError if unknown.
    f = tmp_path / "doc.md"
    f.write_text(
        "---\ndossier_role: whatever-the-consumer-calls-it/appendix-b-style-role\n---\n\nBody.\n",
        encoding="utf-8",
    )
    assert dossier_role.read_dossier_role(f) == "whatever-the-consumer-calls-it/appendix-b-style-role"


def test_coexists_with_renderfact_uid_and_other_keys(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text(
        "---\ntitle: Example\nrenderfact_uid: 11111111-1111-1111-1111-111111111111\n"
        "dossier_role: covers procurement scope; see the annex for pricing detail\n"
        "tags: [a, b]\n---\n\nBody.\n",
        encoding="utf-8",
    )
    assert dossier_role.read_dossier_role(f) == "covers procurement scope; see the annex for pricing detail"


def test_reading_never_mutates_the_file(tmp_path):
    f = tmp_path / "doc.md"
    original = "---\ntitle: Example\n---\n\nBody.\n"
    f.write_text(original, encoding="utf-8")

    dossier_role.read_dossier_role(f)
    dossier_role.read_dossier_role(f)

    assert f.read_text(encoding="utf-8") == original  # byte-for-byte unchanged


def test_malformed_frontmatter_yaml_returns_none_not_an_exception(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("---\ndossier_role: [unterminated\n---\n\nBody.\n", encoding="utf-8")
    assert dossier_role.read_dossier_role(f) is None
