"""
Tests for gates/run_gates.py: the fail-closed QA gate chain (B3a, Vale stage).

Covers: target resolution (files, directories, suffix filtering); the
fail-closed contract with injected fakes (findings -> FAIL, tool absent ->
TOOL_MISSING exit 2, unusable invocation -> fail-closed); NO_FILES honesty;
unknown-stage rejection; config resolution order (flag > env > generic
default); and REAL vale runs (skipped when vale is not installed): the
generic config blocks a repeated word, does not block a spelling warning,
and passes clean prose. Plus the render.py dispatch.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from gates import run_gates  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"
HAVE_VALE = shutil.which("vale") is not None


# ---- target resolution ----

def test_resolve_files_filters_by_suffix_and_walks_dirs(tmp_path):
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("x", encoding="utf-8")
    files = run_gates._resolve_files([str(tmp_path)], (".md",))
    assert [f.name for f in files] == ["a.md", "c.md"]
    files = run_gates._resolve_files([str(tmp_path / "b.txt")], (".md",))
    assert files == []


# ---- fail-closed contract with fakes ----

def _fake_runner(returncode: int, stdout: str = "", stderr: str = ""):
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)
    return runner


def test_vale_stage_missing_tool_is_a_failure_not_a_skip(tmp_path):
    (tmp_path / "doc.md").write_text("text", encoding="utf-8")
    r = run_gates.run_vale([str(tmp_path)], None, which=lambda n: None,
                           runner=_fake_runner(0))
    assert r.status == "TOOL_MISSING"
    assert "FAILED gate" in r.detail


def test_vale_stage_findings_fail(tmp_path):
    (tmp_path / "doc.md").write_text("text", encoding="utf-8")
    r = run_gates.run_vale([str(tmp_path)], None, which=lambda n: "/usr/bin/vale",
                           runner=_fake_runner(1, stdout="doc.md:3:6:Vale.Repetition:'is' is repeated!"))
    assert r.status == "FAIL"
    assert "Repetition" in r.detail


def test_vale_stage_clean_passes(tmp_path):
    (tmp_path / "doc.md").write_text("text", encoding="utf-8")
    r = run_gates.run_vale([str(tmp_path)], None, which=lambda n: "/usr/bin/vale",
                           runner=_fake_runner(0))
    assert r.status == "PASS"


def test_vale_stage_unusable_invocation_fails_closed(tmp_path):
    (tmp_path / "doc.md").write_text("text", encoding="utf-8")
    r = run_gates.run_vale([str(tmp_path)], None, which=lambda n: "/usr/bin/vale",
                           runner=_fake_runner(2, stderr="bad config"))
    assert r.status == "TOOL_MISSING"
    assert "unusable" in r.detail


def test_no_applicable_files_is_reported_not_silently_passed(tmp_path):
    (tmp_path / "doc.txt").write_text("text", encoding="utf-8")
    r = run_gates.run_vale([str(tmp_path)], None, which=lambda n: "/usr/bin/vale",
                           runner=_fake_runner(0))
    assert r.status == "NO_FILES"


def test_unknown_stage_is_exit_2(tmp_path, capsys):
    (tmp_path / "doc.md").write_text("text", encoding="utf-8")
    rc = run_gates.main([str(tmp_path), "--stages", "sonar"])
    assert rc == 2
    assert "unknown stage" in capsys.readouterr().err


# ---- real vale runs (generic-core default config) ----

pytestmark_real = pytest.mark.skipif(not HAVE_VALE, reason="vale not installed on this host")


@pytestmark_real
def test_real_vale_repetition_blocks_with_generic_config(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("# T\n\nThis is is a repeated word.\n", encoding="utf-8")
    rc = run_gates.main([str(bad), "--stages", "vale"])
    assert rc == 1


@pytestmark_real
def test_real_vale_spelling_warns_but_does_not_block(tmp_path):
    warn_only = tmp_path / "warn.md"
    warn_only.write_text("# T\n\nA mispeled word but no repetition.\n", encoding="utf-8")
    rc = run_gates.main([str(warn_only), "--stages", "vale"])
    assert rc == 0  # spelling is warning-level in the generic config


@pytestmark_real
def test_real_vale_clean_prose_passes(tmp_path):
    good = tmp_path / "good.md"
    good.write_text("# T\n\nA clean sentence.\n", encoding="utf-8")
    rc = run_gates.main([str(good), "--stages", "vale"])
    assert rc == 0


@pytestmark_real
def test_render_entrypoint_dispatches_gate_mode(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("# T\n\nthe the doubled.\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "gate", str(bad), "--stages", "vale"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1
    assert "[vale] FAIL" in result.stdout


# ---- lychee stage (B3b) ----
# Exit-code mapping encoded here was verified against the real lychee 0.24.2
# binary (release download): 0 = clean, 2 = broken links, 1 = unusable run.

def test_lychee_missing_tool_is_a_failure_not_a_skip(tmp_path, monkeypatch):
    monkeypatch.delenv("RENDERFACT_LYCHEE_BIN", raising=False)
    (tmp_path / "doc.md").write_text("text", encoding="utf-8")
    r = run_gates.run_lychee([str(tmp_path)], which=lambda n: None,
                             runner=_fake_runner(0))
    assert r.status == "TOOL_MISSING"


def test_lychee_broken_links_fail(tmp_path):
    (tmp_path / "doc.md").write_text("[x](nope.md)", encoding="utf-8")
    r = run_gates.run_lychee([str(tmp_path)], which=lambda n: "/usr/bin/lychee",
                             runner=_fake_runner(2, stdout="[ERROR] file nope.md: not found"))
    assert r.status == "FAIL"
    assert "nope.md" in r.detail


def test_lychee_clean_passes_and_reports_offline_mode(tmp_path):
    (tmp_path / "doc.md").write_text("[x](doc.md)", encoding="utf-8")
    r = run_gates.run_lychee([str(tmp_path)], which=lambda n: "/usr/bin/lychee",
                             runner=_fake_runner(0))
    assert r.status == "PASS"
    assert "offline" in r.detail


def test_lychee_offline_flag_is_default_and_online_removes_it(tmp_path):
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    run_gates.run_lychee([str(tmp_path)], which=lambda n: "/usr/bin/lychee", runner=runner)
    assert "--offline" in seen["cmd"]
    run_gates.run_lychee([str(tmp_path)], online=True,
                         which=lambda n: "/usr/bin/lychee", runner=runner)
    assert "--offline" not in seen["cmd"]


def test_lychee_env_binary_override(tmp_path, monkeypatch):
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    monkeypatch.setenv("RENDERFACT_LYCHEE_BIN", "/custom/lychee")
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    r = run_gates.run_lychee([str(tmp_path)], which=lambda n: None, runner=runner)
    assert r.status == "PASS"
    assert seen["cmd"][0] == "/custom/lychee"


def test_lychee_unusable_invocation_fails_closed(tmp_path):
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    r = run_gates.run_lychee([str(tmp_path)], which=lambda n: "/usr/bin/lychee",
                             runner=_fake_runner(1, stderr="config error"))
    assert r.status == "TOOL_MISSING"
    assert "unusable" in r.detail


# ---- uids stage: duplicate-identity detection (org-scale hygiene) ----

def test_uids_stage_passes_on_unique_and_fails_on_copied_identity(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\ntitle: A\nrenderfact_uid: uid-aaa\n---\n\nBody.\n", encoding="utf-8")
    (tmp_path / "g.yaml").write_text(
        "concepts: []\nrenderfact_uid: uid-bbb\n", encoding="utf-8")
    r = run_gates.run_uids([str(tmp_path)])
    assert r.status == "PASS"
    assert "2 uid-carrying" in r.detail

    # a file copy claims the original's lineage: that is the org-scale hazard
    (tmp_path / "a-copy.md").write_text(
        "---\ntitle: A copy\nrenderfact_uid: uid-aaa\n---\n\nForked body.\n", encoding="utf-8")
    r = run_gates.run_uids([str(tmp_path)])
    assert r.status == "FAIL"
    assert "uid-aaa" in r.detail and "a-copy.md" in r.detail


def test_uids_stage_ignores_sources_without_uid(tmp_path):
    (tmp_path / "plain.md").write_text("# No frontmatter\n", encoding="utf-8")
    r = run_gates.run_uids([str(tmp_path)])
    assert r.status == "PASS"
    assert "0 uid-carrying" in r.detail


# ---- plainlang stage: repeated-phrase-across-sections (issue #76) ----
# Dependency-free, deterministic (same as uids), but UNLIKE every other stage
# a finding is report-only by default: see docstyle/plain_language.py and
# demo/skin/vale/styles/PlainLanguage/README.md for why.

def test_plainlang_stage_no_files(tmp_path):
    (tmp_path / "doc.txt").write_text("text", encoding="utf-8")
    r = run_gates.run_plain_language([str(tmp_path)])
    assert r.status == "NO_FILES"


def test_plainlang_stage_passes_clean(tmp_path):
    (tmp_path / "doc.md").write_text(
        "A short clean document with nothing repeated in it at all.\n", encoding="utf-8")
    r = run_gates.run_plain_language([str(tmp_path)])
    assert r.status == "PASS"
    assert "no repeated phrase" in r.detail


def test_plainlang_stage_finding_is_report_only_by_default(tmp_path):
    (tmp_path / "doc.md").write_text(
        "In the same way as the reference design, section one applies here. "
        "In the same way as the reference design, section two applies here. "
        "In the same way as the reference design, section three applies here.\n",
        encoding="utf-8")
    r = run_gates.run_plain_language([str(tmp_path)])
    assert r.status == "PASS"  # report-only: a hit does not fail the run by default
    assert "repeated phrase" in r.detail
    assert "report-only" in r.detail


def test_plainlang_stage_fail_on_hits_flag_blocks(tmp_path):
    (tmp_path / "doc.md").write_text(
        "In the same way as the reference design, section one applies here. "
        "In the same way as the reference design, section two applies here. "
        "In the same way as the reference design, section three applies here.\n",
        encoding="utf-8")
    r = run_gates.run_plain_language([str(tmp_path)], fail_on_hits=True)
    assert r.status == "FAIL"
    assert "repeated phrase" in r.detail


def test_plainlang_stage_thresholds_are_tunable(tmp_path):
    (tmp_path / "doc.md").write_text(
        "Section one behaves in the same way as the pilot did. "
        "Section two behaves in the same way as the pilot did. "
        "Section three is unrelated and stands on its own.\n",
        encoding="utf-8")
    # Below the default min_count of 3 (only two repeats): clean.
    default_result = run_gates.run_plain_language([str(tmp_path)])
    assert default_result.status == "PASS"
    assert "no repeated phrase" in default_result.detail
    # Lowering min_count to 2 surfaces the same two-repeat phrase.
    r = run_gates.run_plain_language([str(tmp_path)], min_count=2)
    assert "repeated phrase" in r.detail and "report-only" in r.detail


def test_plainlang_stage_unknown_stage_still_rejects(tmp_path, capsys):
    (tmp_path / "doc.md").write_text("text", encoding="utf-8")
    rc = run_gates.main([str(tmp_path), "--stages", "plainlang,bogus"])
    assert rc == 2
    assert "unknown stage" in capsys.readouterr().err


def test_render_entrypoint_dispatches_plainlang_stage_report_only(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(
        "In the same way as the reference design, section one applies here. "
        "In the same way as the reference design, section two applies here. "
        "In the same way as the reference design, section three applies here.\n",
        encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "gate", str(doc), "--stages", "plainlang"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0
    assert "[plainlang] PASS" in result.stdout
    assert "repeated phrase" in result.stdout


def test_render_entrypoint_dispatches_plainlang_fail_on_hits_flag(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(
        "In the same way as the reference design, section one applies here. "
        "In the same way as the reference design, section two applies here. "
        "In the same way as the reference design, section three applies here.\n",
        encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "gate", str(doc), "--stages", "plainlang",
         "--plainlang-fail-on-hits"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1
    assert "[plainlang] FAIL" in result.stdout


# ---- demo skin GoldenRules style (writing doctrine as CONSUMER config) ----

DEMO_VALE_CONFIG = REPO_ROOT / "demo" / "skin" / "vale" / "vale.ini"


@pytestmark_real
def test_demo_skin_style_blocks_throat_clearing(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("# T\n\nIn this section we will discuss things.\n", encoding="utf-8")
    rc = run_gates.main([str(bad), "--stages", "vale", "--vale-config", str(DEMO_VALE_CONFIG)])
    assert rc == 1


@pytestmark_real
def test_demo_skin_hedges_warn_but_do_not_block(tmp_path):
    warn = tmp_path / "warn.md"
    warn.write_text("# T\n\nThe plan is quite ambitious.\n", encoding="utf-8")
    rc = run_gates.main([str(warn), "--stages", "vale", "--vale-config", str(DEMO_VALE_CONFIG)])
    assert rc == 0


@pytestmark_real
def test_demo_source_passes_its_own_skin_rules():
    """The demo dossier must satisfy the demo skin's own writing doctrine
    (dogfood invariant: the README claims it, so a test keeps it true)."""
    rc = run_gates.main([str(REPO_ROOT / "demo" / "source"), "--stages", "vale",
                         "--vale-config", str(DEMO_VALE_CONFIG)])
    assert rc == 0


# ---- demo skin PlainLanguage style (issue #76: reader-facing KISS quality,
# distinct from AiTells' authorial-tell detection) ----

@pytestmark_real
def test_demo_skin_sentence_length_warns_but_does_not_block(tmp_path):
    long_sentence = (
        "This sentence keeps going and going with clause after clause "
        "connected by conjunctions and by commas describing several distinct "
        "ideas in a single breath without ever pausing for a full stop which "
        "is exactly the kind of sentence a plain language reviewer would "
        "want split cleanly in two for an easier read.\n"
    )
    warn = tmp_path / "warn.md"
    warn.write_text("# T\n\n" + long_sentence, encoding="utf-8")
    result = subprocess.run(
        ["vale", "--config", str(DEMO_VALE_CONFIG), "--output", "line", str(warn)],
        capture_output=True, text=True, timeout=60,
    )
    assert "PlainLanguage.SentenceLength" in result.stdout
    rc = run_gates.main([str(warn), "--stages", "vale", "--vale-config", str(DEMO_VALE_CONFIG)])
    assert rc == 0  # warning-level: advisory, does not block the gate


@pytestmark_real
def test_demo_skin_short_sentences_do_not_trigger_sentence_length(tmp_path):
    clean = tmp_path / "clean.md"
    clean.write_text("# T\n\nA short, clear sentence. Another short one follows it.\n",
                     encoding="utf-8")
    result = subprocess.run(
        ["vale", "--config", str(DEMO_VALE_CONFIG), "--output", "line", str(clean)],
        capture_output=True, text=True, timeout=60,
    )
    assert "PlainLanguage.SentenceLength" not in result.stdout


@pytestmark_real
def test_demo_skin_nominalisation_density_warns_but_does_not_block(tmp_path):
    dense = tmp_path / "dense.md"
    dense.write_text(
        "# T\n\nThe migration required careful documentation, coordination "
        "across departments, and eventual agreement on the governance "
        "arrangement, which added extra management overhead to the "
        "procurement declaration.\n",
        encoding="utf-8")
    result = subprocess.run(
        ["vale", "--config", str(DEMO_VALE_CONFIG), "--output", "line", str(dense)],
        capture_output=True, text=True, timeout=60,
    )
    assert "PlainLanguage.NominalisationDensity" in result.stdout
    rc = run_gates.main([str(dense), "--stages", "vale", "--vale-config", str(DEMO_VALE_CONFIG)])
    assert rc == 0  # warning-level: advisory, does not block the gate


@pytestmark_real
def test_demo_skin_low_nominalisation_paragraph_does_not_trigger(tmp_path):
    clean = tmp_path / "clean.md"
    clean.write_text(
        "# T\n\nA short paragraph that names one process and one decision, "
        "nothing more, and stops there.\n",
        encoding="utf-8")
    result = subprocess.run(
        ["vale", "--config", str(DEMO_VALE_CONFIG), "--output", "line", str(clean)],
        capture_output=True, text=True, timeout=60,
    )
    assert "PlainLanguage.NominalisationDensity" not in result.stdout


HAVE_LYCHEE = shutil.which("lychee") is not None


# ---- verapdf stage (B3c) ----
# Exit-code mapping encoded here was verified against the real veraPDF 1.30.2
# CLI (headless izpack install): 0 = all compliant, 1 = non-compliant. Also
# verified live: typst --pdf-standard a-2b output PASSES PDF/A-2b validation;
# a plain PDF auto-detects to PDF/A-1b and fails, correct for an archival gate.

def test_verapdf_missing_tool_is_a_failure_not_a_skip(tmp_path, monkeypatch):
    monkeypatch.delenv("RENDERFACT_VERAPDF_BIN", raising=False)
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.7 stub")
    r = run_gates.run_verapdf([str(tmp_path)], which=lambda n: None,
                              runner=_fake_runner(0))
    assert r.status == "TOOL_MISSING"


def test_verapdf_noncompliant_fails(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.7 stub")
    r = run_gates.run_verapdf([str(tmp_path)], which=lambda n: "/usr/bin/verapdf",
                              runner=_fake_runner(1, stdout="FAIL doc.pdf 1b"))
    assert r.status == "FAIL"
    assert "1b" in r.detail


def test_verapdf_compliant_passes_with_mode_note(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.7 stub")
    r = run_gates.run_verapdf([str(tmp_path)], which=lambda n: "/usr/bin/verapdf",
                              runner=_fake_runner(0, stdout="PASS doc.pdf 2b"))
    assert r.status == "PASS"
    assert "auto-detect" in r.detail


def test_verapdf_flavour_flag_passthrough(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.7 stub")
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    r = run_gates.run_verapdf([str(tmp_path)], flavour="ua1",
                              which=lambda n: "/usr/bin/verapdf", runner=runner)
    assert ["-f", "ua1"] == [seen["cmd"][i] for i in (3, 4)]
    assert "flavour ua1" in r.detail


def test_verapdf_no_pdfs_is_reported(tmp_path):
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    r = run_gates.run_verapdf([str(tmp_path)], which=lambda n: "/usr/bin/verapdf",
                              runner=_fake_runner(0))
    assert r.status == "NO_FILES"


def _verapdf_available() -> bool:
    import os
    return bool(os.environ.get("RENDERFACT_VERAPDF_BIN")) or \
        shutil.which("verapdf") is not None or shutil.which("verapdf.bat") is not None


HAVE_TYPST = shutil.which("typst") is not None


@pytest.mark.skipif(not (_verapdf_available() and HAVE_TYPST),
                    reason="verapdf and/or typst not available on this host")
def test_real_verapdf_passes_typst_pdfa_and_fails_plain(tmp_path):
    src = tmp_path / "doc.typ"
    src.write_text("= Fixture\n\nA paragraph of text.\n", encoding="utf-8")
    pdfa = tmp_path / "pdfa.pdf"
    plain = tmp_path / "plain.pdf"
    subprocess.run(["typst", "compile", "--pdf-standard", "a-2b", str(src), str(pdfa)],
                   check=True, capture_output=True, timeout=120)
    subprocess.run(["typst", "compile", str(src), str(plain)],
                   check=True, capture_output=True, timeout=120)

    assert run_gates.run_verapdf([str(pdfa)]).status == "PASS"
    assert run_gates.run_verapdf([str(plain)]).status == "FAIL"


@pytest.mark.skipif(not HAVE_LYCHEE, reason="lychee not installed on this host")
def test_real_lychee_offline_broken_and_clean(tmp_path):
    (tmp_path / "other.md").write_text("# Other\n", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("[good](other.md) [broken](nope.md) [ext](https://example.com/)\n",
                   encoding="utf-8")
    assert run_gates.run_lychee([str(bad)]).status == "FAIL"
    good = tmp_path / "good.md"
    good.write_text("[good](other.md) [ext](https://example.com/)\n", encoding="utf-8")
    r = run_gates.run_lychee([str(good)])
    assert r.status == "PASS"  # external URL excluded offline: deterministic verdict
