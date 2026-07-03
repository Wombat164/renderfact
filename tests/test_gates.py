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


HAVE_LYCHEE = shutil.which("lychee") is not None


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
