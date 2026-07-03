"""
Tests for the template pack (templates/): five genre sources + committed
identity-free DOCX exemplars.

Covers: the pack invariants that make templates safe to copy (NO renderfact_uid
in any template's frontmatter: a uid on a template would be inherited by every
instantiated copy, the exact duplicate-identity hazard the uids gate exists
for; committed exemplars carry NO provenance because they are rendered with
PROVENANCE=off); every template projects cleanly against the shipped example
profiles for every profile (which also fail-closed-validates every gated
block's ladder values); and the pack passes its own style gate (vale + uids,
skipped without vale on the host).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "roundtrip"))

from projection import projector  # noqa: E402
from roundtrip import provenance  # noqa: E402

TEMPLATES = sorted((REPO_ROOT / "templates").glob("*.md"))
SOURCES = [t for t in TEMPLATES if t.name != "README.md"]
EXEMPLARS = sorted((REPO_ROOT / "templates" / "renders").glob("*.docx"))
EXAMPLE_PROFILES = REPO_ROOT / "projection" / "profiles-example.yaml"


def test_pack_shape():
    assert {t.stem for t in SOURCES} == {
        "executive-summary", "external-party-brief", "pitch-1pager",
        "pitch-5pager", "purchase-request",
    }
    assert {e.stem for e in EXEMPLARS} == {f"{t.stem}-exemplar" for t in SOURCES}


@pytest.mark.parametrize("template", SOURCES, ids=lambda t: t.stem)
def test_template_frontmatter_is_identity_free(template):
    text = template.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert m, f"{template.name}: missing frontmatter"
    fm = yaml.safe_load(m.group(1))
    assert "renderfact_uid" not in fm, (
        f"{template.name} carries an identity: every instantiated copy would "
        f"inherit it (the duplicate-identity hazard)"
    )
    assert fm.get("version") == "v0.1"
    assert fm.get("lang") == "en"


@pytest.mark.parametrize("exemplar", EXEMPLARS, ids=lambda e: e.stem)
def test_committed_exemplars_carry_no_provenance(exemplar):
    assert provenance.extract(exemplar) is None, (
        f"{exemplar.name} carries provenance: exemplars must be rendered with "
        f"PROVENANCE=off (they are nobody's canonical lineage)"
    )


@pytest.mark.parametrize("template", SOURCES, ids=lambda t: t.stem)
def test_template_projects_against_example_profiles(template, tmp_path):
    """Projecting exercises fail-closed ladder validation on every gated block:
    a template using a value outside the example ladders would raise here."""
    ladders, profiles = projector.load_config(EXAMPLE_PROFILES)
    work = tmp_path / template.name
    work.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    for name, prof in profiles.items():
        text, _dropped = projector.project(work, prof, ladders, {})
        assert text.strip(), f"{template.name} projected empty under {name}"
    public, _ = projector.project(work, profiles["public-release"], ladders, {})
    internal, _ = projector.project(work, profiles["internal-full"], ladders, {})
    assert len(internal) > len(public), (
        f"{template.name}: the internal render should carry more than the "
        f"public one (its gated blocks demonstrate the mechanic)"
    )


@pytest.mark.skipif(shutil.which("vale") is None, reason="vale not installed on this host")
def test_pack_passes_its_own_style_gate():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "render.py"), "gate", "templates",
         "--stages", "vale,uids"],
        capture_output=True, text=True, timeout=180, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
