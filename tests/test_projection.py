"""
Tests for projection/projector.py -- the F1 projection engine.

Covers: config loading (valid, missing keys, unknown ladder values -- fail-closed),
fenced-div segment parsing, the full keep_block gate matrix (clearance no-read-up,
distribution extent, unknown-label fail-closed, lang select, audience allow/deny,
disclosure postures for detail/abstract/softspot), gloss injection (first body
occurrence, heading skip, assume/forbid suppression), end-to-end projection against
the shipped example profiles (including stamp_header suppression for the
public-release profile), and CLI dispatch through render.py as a real subprocess.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from projection import projector  # noqa: E402
from projection.projector import ProjectionError  # noqa: E402

EXAMPLE_PROFILES = REPO_ROOT / "projection" / "profiles-example.yaml"

SOURCE = """---
title: Example Dossier
---

# Overview

Intro visible to everyone.

::: {.block clearance="secret" releasable="team"}
Deep internal secret.
:::

::: {.block clearance="internal" releasable="partners"}
Partner-shareable context.
:::

::: {.block detail="true"}
Full-posture-only deep detail.
:::

::: {.block variant="abstract"}
Abstract replacement paragraph.
:::

::: {.block lang="fr"}
Paragraphe en francais.
:::

::: {.block audience="maintainer"}
Maintainer-only note.
:::

::: {.block hide="general"}
Hidden from the general audience.
:::
"""


@pytest.fixture()
def ladders_profiles():
    return projector.load_config(EXAMPLE_PROFILES)


@pytest.fixture()
def source_file(tmp_path):
    f = tmp_path / "dossier.md"
    f.write_text(SOURCE, encoding="utf-8")
    return f


# ---------- config ----------

def test_example_config_loads(ladders_profiles):
    ladders, profiles = ladders_profiles
    assert ladders["clearance"]["public"] == 0
    assert ladders["clearance"]["secret"] == 3
    assert ladders["distribution"]["public"] == 3
    assert set(profiles) == {"internal-full", "partner-brief", "public-release"}


def test_config_rejects_missing_ladders(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("profiles: {x: {}}\n", encoding="utf-8")
    with pytest.raises(ProjectionError, match="ladders"):
        projector.load_config(p)


def test_config_rejects_unknown_ceiling(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "ladders:\n  clearance: [low, high]\n  distribution: [near, far]\n"
        "profiles:\n  x:\n    clearance_ceiling: ultra\n    releasable_to: near\n"
        "    lang: en\n    audience: a\n    disclosure: full\n",
        encoding="utf-8",
    )
    with pytest.raises(ProjectionError, match="ultra"):
        projector.load_config(p)


def test_config_rejects_missing_profile_key(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "ladders:\n  clearance: [low, high]\n  distribution: [near, far]\n"
        "profiles:\n  x:\n    clearance_ceiling: low\n    releasable_to: near\n"
        "    lang: en\n    audience: a\n",  # no disclosure
        encoding="utf-8",
    )
    with pytest.raises(ProjectionError, match="disclosure"):
        projector.load_config(p)


# ---------- parsing ----------

def test_parse_segments_splits_text_and_blocks():
    segs = projector.parse_segments(
        'before\n::: {.block clearance="secret" lang="en"}\ninside\n:::\nafter'
    )
    kinds = [s[0] for s in segs]
    assert kinds == ["text", "block", "text"]
    assert segs[1][1] == {"clearance": "secret", "lang": "en"}
    assert segs[1][2] == "inside"


# ---------- keep_block gate matrix ----------

def _prof(ladders, **overrides):
    prof = {
        "_name": "t", "clearance_ceiling": "confidential", "releasable_to": "partners",
        "lang": "en", "audience": "reviewer", "disclosure": "contextual",
    }
    prof.update(overrides)
    return prof


def test_clearance_no_read_up(ladders_profiles):
    ladders, _ = ladders_profiles
    prof = _prof(ladders)
    assert not projector.keep_block({"clearance": "secret"}, prof, ladders)
    assert projector.keep_block({"clearance": "confidential"}, prof, ladders)
    assert projector.keep_block({}, prof, ladders)  # unlabelled = lowest rank


def test_unknown_clearance_fails_closed(ladders_profiles):
    ladders, _ = ladders_profiles
    with pytest.raises(ProjectionError, match="block clearance"):
        projector.keep_block({"clearance": "ultra"}, _prof(ladders), ladders)


def test_distribution_extent_gate(ladders_profiles):
    ladders, _ = ladders_profiles
    prof = _prof(ladders, releasable_to="partners")
    assert not projector.keep_block({"releasable": "team"}, prof, ladders)
    assert projector.keep_block({"releasable": "partners"}, prof, ladders)
    assert projector.keep_block({"releasable": "public"}, prof, ladders)
    assert projector.keep_block({}, prof, ladders)  # unlabelled = unrestricted


def test_lang_select(ladders_profiles):
    ladders, _ = ladders_profiles
    prof = _prof(ladders, lang="en")
    assert not projector.keep_block({"lang": "fr"}, prof, ladders)
    assert projector.keep_block({"lang": "en"}, prof, ladders)
    assert projector.keep_block({}, prof, ladders)  # language-neutral


def test_audience_allow_and_deny_lists(ladders_profiles):
    ladders, _ = ladders_profiles
    prof = _prof(ladders, audience="reviewer")
    assert projector.keep_block({"audience": "reviewer, maintainer"}, prof, ladders)
    assert not projector.keep_block({"audience": "maintainer"}, prof, ladders)
    assert not projector.keep_block({"hide": "reviewer"}, prof, ladders)
    assert projector.keep_block({"hide": "general"}, prof, ladders)


def test_disclosure_postures(ladders_profiles):
    ladders, _ = ladders_profiles
    full = _prof(ladders, disclosure="full")
    contextual = _prof(ladders, disclosure="contextual")
    minimal = _prof(ladders, disclosure="minimal")
    assert projector.keep_block({"detail": "true"}, full, ladders)
    assert not projector.keep_block({"detail": "true"}, contextual, ladders)
    assert not projector.keep_block({"variant": "abstract"}, full, ladders)
    assert projector.keep_block({"variant": "abstract"}, contextual, ladders)
    assert projector.keep_block({"softspot": "true"}, contextual, ladders)
    assert not projector.keep_block({"softspot": "true"}, minimal, ladders)


# ---------- gloss injection ----------

def test_gloss_injects_first_body_occurrence_only():
    bank = {"CMDB": {"gloss": "configuration database", "assume": set(), "forbid": set()}}
    text = "# CMDB heading\nThe CMDB holds items.\nThe CMDB again."
    out = projector.gloss_inject(text, "general", bank)
    assert "# CMDB heading" in out  # heading untouched
    assert "CMDB (configuration database) holds" in out
    assert out.count("(configuration database)") == 1


def test_gloss_skips_assume_and_forbid_audiences():
    bank = {
        "CMDB": {"gloss": "configuration database", "assume": {"expert"}, "forbid": {"outsider"}},
    }
    text = "The CMDB holds items."
    assert projector.gloss_inject(text, "expert", bank) == text
    assert projector.gloss_inject(text, "outsider", bank) == text


# ---------- end-to-end projection ----------

def test_internal_full_keeps_everything_except_abstract_and_fr(source_file, ladders_profiles):
    ladders, profiles = ladders_profiles
    text, dropped = projector.project(source_file, profiles["internal-full"], ladders, {})
    # maintainer/full/en/secret/team: drops abstract variant, fr block, hidden-from
    # applies only to 'general', audience allow-list includes maintainer
    assert "Deep internal secret." in text
    assert "Full-posture-only deep detail." in text
    assert "Maintainer-only note." in text
    assert "Abstract replacement paragraph." not in text
    assert "francais" not in text
    assert dropped == 2
    assert text.startswith("<!-- projected: profile=internal-full")


def test_public_release_strips_and_suppresses_stamp(source_file, ladders_profiles):
    ladders, profiles = ladders_profiles
    text, dropped = projector.project(source_file, profiles["public-release"], ladders, {})
    assert "Intro visible to everyone." in text
    assert "Deep internal secret." not in text
    assert "Partner-shareable context." not in text  # releasable=partners < public travel
    assert "Maintainer-only note." not in text
    assert "Hidden from the general audience." not in text
    assert "Abstract replacement paragraph." in text
    assert "<!-- projected:" not in text  # stamp_header: false (D14 audience-awareness)


def test_keep_frontmatter_reattaches_source_frontmatter(source_file, ladders_profiles):
    ladders, profiles = ladders_profiles
    text, _ = projector.project(source_file, profiles["internal-full"], ladders, {}, keep_fm=True)
    assert text.startswith("---\ntitle: Example Dossier\n---\n")


def test_dropping_frontmatter_without_keep_flag_warns(source_file, ladders_profiles, capsys):
    ladders, profiles = ladders_profiles
    projector.project(source_file, profiles["internal-full"], ladders, {})  # keep_fm defaults False
    err = capsys.readouterr().err
    assert "NOTE" in err
    assert "--keep-frontmatter" in err


def test_keeping_frontmatter_prints_no_warning(source_file, ladders_profiles, capsys):
    ladders, profiles = ladders_profiles
    projector.project(source_file, profiles["internal-full"], ladders, {}, keep_fm=True)
    assert capsys.readouterr().err == ""


def test_source_without_frontmatter_prints_no_warning(tmp_path, ladders_profiles, capsys):
    ladders, profiles = ladders_profiles
    no_fm = tmp_path / "no-frontmatter.md"
    no_fm.write_text("# Overview\n\nJust body text, no YAML block.\n", encoding="utf-8")
    projector.project(no_fm, profiles["internal-full"], ladders, {})
    assert capsys.readouterr().err == ""


# ---------- CLI ----------

def test_cli_single_profile_writes_file(source_file, tmp_path):
    out = tmp_path / "out.md"
    rc = projector.main([str(source_file), "--profiles", str(EXAMPLE_PROFILES),
                         "--profile", "partner-brief", "-o", str(out)])
    assert rc == 0
    assert "Partner-shareable context." in out.read_text(encoding="utf-8")


def test_cli_all_writes_one_file_per_profile(source_file, tmp_path):
    rc = projector.main([str(source_file), "--profiles", str(EXAMPLE_PROFILES),
                         "--all", "--output-dir", str(tmp_path / "renders")])
    assert rc == 0
    names = {p.name for p in (tmp_path / "renders").glob("*.md")}
    assert names == {"dossier--internal-full.md", "dossier--partner-brief.md",
                     "dossier--public-release.md"}


def test_cli_unknown_profile_is_clean_error(source_file, capsys):
    rc = projector.main([str(source_file), "--profiles", str(EXAMPLE_PROFILES),
                         "--profile", "nope"])
    assert rc == 1
    assert "unknown profile" in capsys.readouterr().err


def test_render_entrypoint_dispatches_project_mode(source_file, tmp_path):
    out = tmp_path / "via-dispatch.md"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "render.py"), "project", str(source_file),
         "--profiles", str(EXAMPLE_PROFILES), "--profile", "public-release",
         "-o", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert "Deep internal secret." not in out.read_text(encoding="utf-8")


# ---- D14: strip_provenance profile key ----

def test_config_rejects_non_bool_strip_provenance(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        'ladders:\n  clearance: [low, high]\n  distribution: [near, far]\n'
        'profiles:\n  x:\n    clearance_ceiling: low\n    releasable_to: near\n'
        '    lang: en\n    audience: a\n    disclosure: full\n'
        '    strip_provenance: "external"\n',
        encoding="utf-8",
    )
    with pytest.raises(ProjectionError, match="strip_provenance"):
        projector.load_config(p)


def test_example_public_release_profile_strips_provenance(ladders_profiles):
    _, profiles = ladders_profiles
    assert profiles["public-release"]["strip_provenance"] is True
    assert "strip_provenance" not in profiles["internal-full"]  # default: full provenance
